"""Organizations, members and invitations (S09, T1.3).

Every mutation writes exactly one audit row in the same transaction (app.services.audit).
Isolation is enforced twice: queries filter by `ctx.organization_id` and RLS filters again.
"""

import hashlib
import secrets
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import (
    AlreadyMember,
    Conflict,
    Forbidden,
    InvitationEmailMismatch,
    InvitationExpired,
    LastOwner,
    NotFound,
    SlugTaken,
    ValidationFailed,
)
from app.auth.authorization import RequestContext, has_permission
from app.auth.permissions import Permission, SystemRole, system_role_id
from app.db.base import new_uuid
from app.db.models import (
    GroupMembership,
    Invitation,
    Membership,
    Organization,
    Role,
    RolePermission,
    User,
)
from app.db.tenant import set_tenant_context
from app.domain.schemas.common import Page
from app.domain.schemas.identity import (
    InvitationAccepted,
    InvitationCreate,
    InvitationOut,
    MemberOut,
    OrganizationCreate,
    OrganizationOut,
)
from app.services import audit
from app.services.pagination import after_cursor, encode_cursor, page_limit
from app.services.users import AuthenticatedUser

OWNER = SystemRole.OWNER.value


# --------------------------------------------------------------------------- organizations


def _org_out(org: Organization) -> OrganizationOut:
    return OrganizationOut(
        id=org.id, name=org.name, slug=org.slug, status=org.status, created_at=org.created_at
    )


async def list_organizations(
    session: AsyncSession, user: AuthenticatedUser
) -> list[OrganizationOut]:
    """Active organizations the caller is an active member of (RLS: member_read policy)."""
    orgs = await session.scalars(
        select(Organization)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(
            Membership.user_id == user.id,
            Membership.status == "active",
            Organization.status == "active",
        )
        .order_by(Organization.name, Organization.id)
    )
    return [_org_out(o) for o in orgs]


async def create_organization(
    session: AsyncSession, user: AuthenticatedUser, body: OrganizationCreate, request_id: str | None
) -> OrganizationOut:
    """Create the org and make the caller its owner. The org's id is chosen first so the
    transaction can enter its RLS context before inserting (no bypass needed)."""
    org_id = new_uuid()
    await set_tenant_context(session, org_id, user.id)
    org = Organization(id=org_id, name=body.name, slug=body.slug)
    session.add(org)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        raise SlugTaken from exc
    session.add(
        Membership(
            id=new_uuid(),
            organization_id=org_id,
            user_id=user.id,
            role_id=system_role_id(SystemRole.OWNER),
        )
    )
    ctx = RequestContext(
        user_id=user.id,
        organization_id=org_id,
        role=OWNER,
        permissions=frozenset(Permission),
        group_ids=frozenset(),
        request_id=request_id,
    )
    await audit.record(session, ctx, "org.created", "organization", org_id, {"slug": body.slug})
    await session.refresh(org)
    return _org_out(org)


# --------------------------------------------------------------------------- roles


async def _resolve_role(session: AsyncSession, organization_id: uuid.UUID, key: str) -> Role:
    """A role usable in this org: the org's own custom role wins over a system role."""
    role = await session.scalar(
        select(Role)
        .where(
            Role.key == key,
            or_(Role.organization_id == organization_id, Role.organization_id.is_(None)),
        )
        .order_by(Role.organization_id.is_(None))  # custom (False) before system (True)
        .limit(1)
    )
    if role is None:
        raise ValidationFailed("Unknown role.", details={"role": key})
    return role


def _require_owner_power(ctx: RequestContext) -> None:
    """Granting or taking away the owner role needs owner-level permission (no escalation)."""
    if not has_permission(ctx, Permission.ORG_MANAGE):
        raise Forbidden(
            "Only owners can grant or remove the owner role.",
            details={"permission": Permission.ORG_MANAGE.value},
        )


async def _lock_owner_count(session: AsyncSession, organization_id: uuid.UUID) -> int:
    """Count active owners while locking their rows, so two concurrent demotions serialize
    instead of both seeing "another owner exists"."""
    rows = await session.scalars(
        select(Membership.id)
        .join(Role, Role.id == Membership.role_id)
        .where(
            Membership.organization_id == organization_id,
            Membership.status == "active",
            Role.key == OWNER,
            Role.organization_id.is_(None),
        )
        .with_for_update(of=Membership)
    )
    return len(rows.all())


# --------------------------------------------------------------------------- members


def _members_query(organization_id: uuid.UUID) -> Any:
    group_ids = func.coalesce(
        func.array_agg(GroupMembership.group_id).filter(GroupMembership.group_id.is_not(None)),
        [],
    )
    return (
        select(
            Membership.id,
            Membership.created_at,
            Membership.user_id,
            User.email,
            User.display_name,
            Role.key,
            Membership.status,
            Membership.joined_at,
            User.last_seen_at,
            group_ids.label("group_ids"),
        )
        .join(User, User.id == Membership.user_id)
        .join(Role, Role.id == Membership.role_id)
        .outerjoin(
            GroupMembership,
            (GroupMembership.user_id == Membership.user_id)
            & (GroupMembership.organization_id == Membership.organization_id),
        )
        .where(Membership.organization_id == organization_id)
        .group_by(Membership.id, User.id, Role.key)
        .order_by(Membership.created_at, Membership.id)
    )


def _member_page(rows: Sequence[Any], limit: int) -> Page[MemberOut]:
    items = [
        MemberOut(
            user_id=r.user_id,
            email=r.email,
            display_name=r.display_name,
            role=r.key,
            status=r.status,
            group_ids=sorted(r.group_ids),
            joined_at=r.joined_at,
            last_seen_at=r.last_seen_at,
        )
        for r in rows[:limit]
    ]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page[MemberOut](items=items, next_cursor=next_cursor)


async def list_members(
    session: AsyncSession,
    ctx: RequestContext,
    *,
    cursor: str | None,
    limit: int,
    group_id: uuid.UUID | None = None,
) -> Page[MemberOut]:
    limit = page_limit(limit)
    query = _members_query(ctx.organization_id)
    if (clause := after_cursor(Membership.created_at, Membership.id, cursor)) is not None:
        query = query.where(clause)
    if group_id is not None:
        in_group = select(GroupMembership.user_id).where(
            GroupMembership.group_id == group_id,
            GroupMembership.organization_id == ctx.organization_id,
        )
        query = query.where(Membership.user_id.in_(in_group))
    rows = list((await session.execute(query.limit(limit + 1))).all())
    return _member_page(rows, limit)


async def _get_member(session: AsyncSession, ctx: RequestContext, user_id: uuid.UUID) -> MemberOut:
    rows = list(
        (
            await session.execute(
                _members_query(ctx.organization_id).where(Membership.user_id == user_id)
            )
        ).all()
    )
    if not rows:
        raise NotFound("The member was not found.")
    return _member_page(rows, 1).items[0]


async def _membership_with_role(
    session: AsyncSession, ctx: RequestContext, user_id: uuid.UUID
) -> tuple[Membership, Role]:
    row = (
        await session.execute(
            select(Membership, Role)
            .join(Role, Role.id == Membership.role_id)
            .where(Membership.organization_id == ctx.organization_id, Membership.user_id == user_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFound("The member was not found.")
    return row[0], row[1]


async def update_member_role(
    session: AsyncSession, ctx: RequestContext, user_id: uuid.UUID, role_key: str
) -> MemberOut:
    membership, current = await _membership_with_role(session, ctx, user_id)
    new_role = await _resolve_role(session, ctx.organization_id, role_key)
    if new_role.id == current.id:
        return await _get_member(session, ctx, user_id)  # no change, no audit row
    if OWNER in (current.key, new_role.key):
        _require_owner_power(ctx)
    if current.key == OWNER and await _lock_owner_count(session, ctx.organization_id) <= 1:
        raise LastOwner
    membership.role_id = new_role.id
    await audit.record(
        session,
        ctx,
        "member.role_changed",
        "membership",
        user_id,
        {"from": current.key, "to": new_role.key},
    )
    return await _get_member(session, ctx, user_id)


async def remove_member(session: AsyncSession, ctx: RequestContext, user_id: uuid.UUID) -> None:
    membership, role = await _membership_with_role(session, ctx, user_id)
    if role.key == OWNER:
        _require_owner_power(ctx)
        if await _lock_owner_count(session, ctx.organization_id) <= 1:
            raise LastOwner
    await session.execute(
        delete(GroupMembership).where(
            GroupMembership.organization_id == ctx.organization_id,
            GroupMembership.user_id == user_id,
        )
    )
    await session.delete(membership)
    await audit.record(session, ctx, "member.removed", "membership", user_id, {"role": role.key})


# --------------------------------------------------------------------------- invitations


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def create_invitation(
    session: AsyncSession,
    ctx: RequestContext,
    body: InvitationCreate,
    *,
    ttl: timedelta,
    web_base_url: str,
) -> InvitationOut:
    role = await _resolve_role(session, ctx.organization_id, body.role)
    if role.key == OWNER:
        _require_owner_power(ctx)
    email = str(body.email).lower()
    already = await session.scalar(
        select(Membership.id)
        .join(User, User.id == Membership.user_id)
        .where(Membership.organization_id == ctx.organization_id, func.lower(User.email) == email)
    )
    if already is not None:
        raise AlreadyMember

    now = datetime.now(UTC)
    # A new invitation supersedes earlier pending ones for the same address.
    await session.execute(
        update(Invitation)
        .where(
            Invitation.organization_id == ctx.organization_id,
            func.lower(Invitation.email) == email,
            Invitation.accepted_at.is_(None),
            Invitation.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    token = secrets.token_urlsafe(32)
    invitation = Invitation(
        id=new_uuid(),
        organization_id=ctx.organization_id,
        email=email,
        role_id=role.id,
        token_hash=_hash_token(token),
        invited_by=ctx.user_id,
        expires_at=now + ttl,
    )
    session.add(invitation)
    await audit.record(
        session, ctx, "member.invited", "invitation", invitation.id, {"role": role.key}
    )
    return InvitationOut(
        id=invitation.id,
        email=email,
        role=role.key,
        expires_at=invitation.expires_at,
        accept_url=f"{web_base_url.rstrip('/')}/invitations/{token}",
    )


async def accept_invitation(
    session: AsyncSession, user: AuthenticatedUser, token: str, request_id: str | None
) -> InvitationAccepted:
    """Join the org of a valid invitation. The caller isn't a member yet, so RLS only reveals the
    invitation whose hash matches the token in this transaction (token_holder_read policy)."""
    await session.execute(
        select(func.set_config("app.invitation_token_hash", _hash_token(token), True))
    )
    invitation = await session.scalar(
        select(Invitation).where(Invitation.token_hash == _hash_token(token))
    )
    if invitation is None or invitation.revoked_at is not None:
        raise NotFound("The invitation was not found.")
    if invitation.email.lower() != (user.email or "").lower():
        raise InvitationEmailMismatch

    await set_tenant_context(session, invitation.organization_id, user.id)
    role = await session.scalar(select(Role).where(Role.id == invitation.role_id))
    org_active = await session.scalar(
        select(Organization.id).where(
            Organization.id == invitation.organization_id, Organization.status == "active"
        )
    )
    if role is None or org_active is None:
        raise NotFound("The invitation was not found.")
    accepted = InvitationAccepted(organization_id=invitation.organization_id, role=role.key)

    existing = await session.scalar(
        select(Membership).where(
            Membership.organization_id == invitation.organization_id,
            Membership.user_id == user.id,
        )
    )
    if invitation.accepted_at is not None:
        if existing is not None:
            return accepted  # retrying the accept link is harmless
        raise Conflict("This invitation was already used.")
    if invitation.expires_at <= datetime.now(UTC):
        raise InvitationExpired
    if existing is not None:
        raise AlreadyMember

    session.add(
        Membership(
            id=new_uuid(),
            organization_id=invitation.organization_id,
            user_id=user.id,
            role_id=role.id,
        )
    )
    invitation.accepted_at = datetime.now(UTC)
    permissions = await session.scalars(
        select(RolePermission.permission).where(RolePermission.role_id == role.id)
    )
    known = {p.value for p in Permission}
    ctx = RequestContext(
        user_id=user.id,
        organization_id=invitation.organization_id,
        role=role.key,
        permissions=frozenset(Permission(p) for p in permissions if p in known),
        group_ids=frozenset(),
        request_id=request_id,
    )
    await audit.record(
        session, ctx, "member.joined", "membership", user.id, {"invitation_id": str(invitation.id)}
    )
    return accepted


__all__ = [
    "accept_invitation",
    "create_invitation",
    "create_organization",
    "list_members",
    "list_organizations",
    "remove_member",
    "update_member_role",
]
