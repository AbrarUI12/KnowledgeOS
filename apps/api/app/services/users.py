"""User provisioning and the `/v1/me` view (T1.1).

Users are created just in time on their first authenticated request, keyed by (issuer, subject):
email is mutable profile data, never an identity key (plan §7.2).
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import Permission
from app.db.base import new_uuid
from app.db.models import Membership, Organization, Role, RolePermission, User
from app.domain.schemas.identity import MembershipOut, MeResponse, UserOut
from app.providers.identity.base import VerifiedToken


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    id: uuid.UUID
    issuer: str
    subject: str
    email: str | None
    display_name: str | None
    status: str
    # Only an IdP-verified email may be used for email-based authorization (invitations).
    email_verified: bool = False

    @property
    def is_active(self) -> bool:
        return self.status == "active"


async def provision_user(
    session: AsyncSession, token: VerifiedToken, *, last_seen_interval: timedelta
) -> AuthenticatedUser:
    """Insert or update the user for this token. Idempotent and safe under concurrency."""
    now = datetime.now(UTC)
    base = insert(User).values(
        id=new_uuid(),
        issuer=token.issuer,
        external_subject=token.subject,
        email=token.email,
        display_name=token.name,
        last_seen_at=now,
    )
    stmt = base.on_conflict_do_update(
        index_elements=[User.issuer, User.external_subject],
        # Profile fields follow the IdP; keep the old value if the token omits a claim.
        set_={
            "email": func.coalesce(base.excluded.email, User.email),
            "display_name": func.coalesce(base.excluded.display_name, User.display_name),
        },
    ).returning(User.id, User.email, User.display_name, User.status, User.last_seen_at)
    row = (await session.execute(stmt)).one()

    # Throttle last_seen writes: one per interval per user, not one per request.
    if row.last_seen_at is None or now - row.last_seen_at > last_seen_interval:
        await session.execute(update(User).where(User.id == row.id).values(last_seen_at=now))

    return AuthenticatedUser(
        id=row.id,
        issuer=token.issuer,
        subject=token.subject,
        email=row.email,
        display_name=row.display_name,
        status=row.status,
        email_verified=token.claims.get("email_verified") is True,
    )


async def load_me(session: AsyncSession, user: AuthenticatedUser) -> MeResponse:
    """The user plus active memberships in active organizations, with effective permissions."""
    rows = (
        await session.execute(
            select(
                Organization.id,
                Organization.name,
                Organization.slug,
                Role.key,
                func.coalesce(
                    func.array_agg(RolePermission.permission).filter(
                        RolePermission.permission.is_not(None)
                    ),
                    [],
                ).label("permissions"),
            )
            .join(Membership, Membership.organization_id == Organization.id)
            .join(Role, Role.id == Membership.role_id)
            .outerjoin(RolePermission, RolePermission.role_id == Role.id)
            .where(
                Membership.user_id == user.id,
                Membership.status == "active",
                Organization.status == "active",
            )
            .group_by(Organization.id, Organization.name, Organization.slug, Role.key)
            .order_by(Organization.name)
        )
    ).all()

    known = {p.value for p in Permission}
    memberships = [
        MembershipOut(
            organization_id=org_id,
            organization_name=name,
            organization_slug=slug,
            role=role_key,
            permissions=sorted(Permission(p) for p in permissions if p in known),
        )
        for org_id, name, slug, role_key, permissions in rows
    ]
    return MeResponse(
        user=UserOut(id=user.id, email=user.email, display_name=user.display_name),
        memberships=memberships,
    )
