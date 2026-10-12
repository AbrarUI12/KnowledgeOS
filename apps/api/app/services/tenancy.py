"""Tenant resolution: active membership → RequestContext, then the RLS context is set (S08).

Isolation is enforced twice: these queries filter by organization explicitly, and RLS filters
again in PostgreSQL. A caller who isn't an active member of an active organization gets None,
which the API turns into 404 so the organization's existence doesn't leak.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import RequestContext
from app.auth.permissions import Permission
from app.db.models import GroupMembership, Membership, Organization, Role, RolePermission
from app.db.tenant import set_tenant_context


async def resolve_request_context(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    request_id: str | None = None,
) -> RequestContext | None:
    """Verify an active membership and switch the transaction into the organization's context.

    Must run after the user context is set (app.user_id): before an organization is chosen, RLS
    only shows the caller's own memberships and the organizations they belong to.
    """
    membership = (
        await session.execute(
            select(Role.id, Role.key)
            .select_from(Membership)
            .join(Organization, Organization.id == Membership.organization_id)
            .join(Role, Role.id == Membership.role_id)
            .where(
                Membership.organization_id == organization_id,
                Membership.user_id == user_id,
                Membership.status == "active",
                Organization.status == "active",
            )
        )
    ).one_or_none()
    if membership is None:
        return None
    role_id, role_key = membership

    permissions = (
        await session.scalars(
            select(RolePermission.permission).where(RolePermission.role_id == role_id)
        )
    ).all()

    await set_tenant_context(session, organization_id, user_id)

    group_ids = (
        await session.scalars(
            select(GroupMembership.group_id).where(
                GroupMembership.organization_id == organization_id,
                GroupMembership.user_id == user_id,
            )
        )
    ).all()

    known = {p.value for p in Permission}
    return RequestContext(
        user_id=user_id,
        organization_id=organization_id,
        role=role_key,
        permissions=frozenset(Permission(p) for p in permissions if p in known),
        group_ids=frozenset(group_ids),
        request_id=request_id,
    )
