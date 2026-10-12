"""Identity & organization endpoints (contracts from T1.0; implemented in T1.1 and T1.3).

Routes validate, check permissions and delegate to services. Reads need membership only;
mutations need the listed permission.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.api.dependencies.auth import CurrentUser
from app.api.dependencies.tenancy import OrgContext, require_permission
from app.api.middleware import current_request_id
from app.api.v1._stub import ERRORS, IdempotencyKeyHeader
from app.auth.authorization import RequestContext
from app.auth.permissions import Permission
from app.db.session import DbSession
from app.domain.schemas.common import Page
from app.domain.schemas.identity import (
    GroupCreate,
    GroupMemberAdd,
    GroupOut,
    GroupUpdate,
    InvitationAccepted,
    InvitationCreate,
    InvitationOut,
    MemberOut,
    MemberUpdate,
    MeResponse,
    OrganizationCreate,
    OrganizationOut,
)
from app.services import groups, idempotency, organizations
from app.services.users import load_me

router = APIRouter(responses=ERRORS)

Cursor = Annotated[str | None, Query(description="Opaque cursor from a previous page")]
Limit = Annotated[int, Query(ge=1, le=100)]
ManageMembers = Annotated[RequestContext, require_permission(Permission.MEMBERS_MANAGE)]
ManageGroups = Annotated[RequestContext, require_permission(Permission.GROUPS_MANAGE)]


async def _idempotent[T: BaseModel](
    request: Request,
    session: DbSession,
    user_id: uuid.UUID,
    key: str | None,
    body: BaseModel,
    status_code: int,
    work: Callable[[], Awaitable[T]],
) -> T | JSONResponse:
    """Run `work` once per Idempotency-Key; a replay returns the stored response verbatim."""
    if key is None:
        return await work()
    ttl = timedelta(hours=request.app.state.settings.idempotency_ttl_hours)
    fingerprint = idempotency.fingerprint(
        request.method, request.url.path, body.model_dump(mode="json")
    )
    stored = await idempotency.begin(
        session, user_id=user_id, key=key, request_fingerprint=fingerprint, ttl=ttl
    )
    if stored is not None:
        return JSONResponse(stored.body, status_code=stored.status_code)
    result = await work()
    await idempotency.complete(
        session, user_id=user_id, key=key, status_code=status_code, body=jsonable_encoder(result)
    )
    return result


# --------------------------------------------------------------------------- me & organizations


@router.get("/me", tags=["me"], response_model=MeResponse)
async def get_me(user: CurrentUser, session: DbSession) -> MeResponse:
    """The authenticated user and their organization memberships with effective permissions."""
    return await load_me(session, user)


@router.get("/organizations", tags=["organizations"], response_model=list[OrganizationOut])
async def list_organizations(user: CurrentUser, session: DbSession) -> list[OrganizationOut]:
    """Organizations the caller is an active member of."""
    return await organizations.list_organizations(session, user)


@router.post(
    "/organizations",
    tags=["organizations"],
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    request: Request,
    user: CurrentUser,
    session: DbSession,
    body: OrganizationCreate,
    idempotency_key: IdempotencyKeyHeader = None,
) -> OrganizationOut | JSONResponse:
    """Create an organization; the caller becomes its owner (409 `slug_taken`).
    Supports `Idempotency-Key`."""
    return await _idempotent(
        request,
        session,
        user.id,
        idempotency_key,
        body,
        status.HTTP_201_CREATED,
        lambda: organizations.create_organization(
            session, user, body, current_request_id(request.scope)
        ),
    )


# --------------------------------------------------------------------------- members


@router.get("/organizations/{org_id}/members", tags=["members"], response_model=Page[MemberOut])
async def list_members(
    org_id: uuid.UUID,
    ctx: OrgContext,
    session: DbSession,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> Page[MemberOut]:
    """Members of the organization (any member may list them)."""
    return await organizations.list_members(session, ctx, cursor=cursor, limit=limit)


@router.patch(
    "/organizations/{org_id}/members/{user_id}", tags=["members"], response_model=MemberOut
)
async def update_member(
    org_id: uuid.UUID,
    ctx: ManageMembers,
    session: DbSession,
    user_id: uuid.UUID,
    body: MemberUpdate,
) -> MemberOut:
    """Change a member's role (`members.manage`). Granting or removing `owner` needs
    `org.manage`; the last owner can't be demoted (409 `last_owner`)."""
    return await organizations.update_member_role(session, ctx, user_id, body.role)


@router.delete(
    "/organizations/{org_id}/members/{user_id}",
    tags=["members"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    org_id: uuid.UUID, ctx: ManageMembers, session: DbSession, user_id: uuid.UUID
) -> None:
    """Remove a member and their group memberships (`members.manage`; 409 `last_owner`)."""
    await organizations.remove_member(session, ctx, user_id)


# --------------------------------------------------------------------------- invitations


@router.post(
    "/organizations/{org_id}/invitations",
    tags=["invitations"],
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(
    request: Request,
    org_id: uuid.UUID,
    ctx: ManageMembers,
    session: DbSession,
    body: InvitationCreate,
) -> InvitationOut:
    """Invite by email (`members.manage`); returns a one-time `accept_url` (the token is stored
    hashed). 409 `already_member`. No `Idempotency-Key`: a replay would have to persist the token.
    A retry instead issues a fresh link and revokes the earlier pending one."""
    settings = request.app.state.settings
    return await organizations.create_invitation(
        session,
        ctx,
        body,
        ttl=timedelta(hours=settings.invitation_ttl_hours),
        web_base_url=settings.web_base_url,
    )


@router.post("/invitations/{token}/accept", tags=["invitations"], response_model=InvitationAccepted)
async def accept_invitation(
    request: Request, token: str, user: CurrentUser, session: DbSession
) -> InvitationAccepted:
    """Join the inviting organization. The signed-in email must match the invitation
    (403 `invitation_email_mismatch`); 410 `invitation_expired`."""
    return await organizations.accept_invitation(
        session, user, token, current_request_id(request.scope)
    )


# --------------------------------------------------------------------------- groups


@router.get("/organizations/{org_id}/groups", tags=["groups"], response_model=Page[GroupOut])
async def list_groups(
    org_id: uuid.UUID,
    ctx: OrgContext,
    session: DbSession,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> Page[GroupOut]:
    return await groups.list_groups(session, ctx, cursor=cursor, limit=limit)


@router.post(
    "/organizations/{org_id}/groups",
    tags=["groups"],
    response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(
    request: Request,
    org_id: uuid.UUID,
    ctx: ManageGroups,
    session: DbSession,
    body: GroupCreate,
    idempotency_key: IdempotencyKeyHeader = None,
) -> GroupOut | JSONResponse:
    """Create a group (`groups.manage`; 409 `group_name_taken`). Supports `Idempotency-Key`."""
    return await _idempotent(
        request,
        session,
        ctx.user_id,
        idempotency_key,
        body,
        status.HTTP_201_CREATED,
        lambda: groups.create_group(session, ctx, body),
    )


@router.patch("/organizations/{org_id}/groups/{group_id}", tags=["groups"], response_model=GroupOut)
async def update_group(
    org_id: uuid.UUID,
    ctx: ManageGroups,
    session: DbSession,
    group_id: uuid.UUID,
    body: GroupUpdate,
) -> GroupOut:
    return await groups.update_group(session, ctx, group_id, body)


@router.delete(
    "/organizations/{org_id}/groups/{group_id}",
    tags=["groups"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_group(
    org_id: uuid.UUID, ctx: ManageGroups, session: DbSession, group_id: uuid.UUID
) -> None:
    await groups.delete_group(session, ctx, group_id)


@router.get(
    "/organizations/{org_id}/groups/{group_id}/members",
    tags=["groups"],
    response_model=Page[MemberOut],
)
async def list_group_members(
    org_id: uuid.UUID,
    ctx: OrgContext,
    session: DbSession,
    group_id: uuid.UUID,
    cursor: Cursor = None,
    limit: Limit = 50,
) -> Page[MemberOut]:
    await groups.ensure_group(session, ctx, group_id)
    return await organizations.list_members(
        session, ctx, cursor=cursor, limit=limit, group_id=group_id
    )


@router.post(
    "/organizations/{org_id}/groups/{group_id}/members",
    tags=["groups"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def add_group_member(
    org_id: uuid.UUID,
    ctx: ManageGroups,
    session: DbSession,
    group_id: uuid.UUID,
    body: GroupMemberAdd,
) -> None:
    await groups.add_member(session, ctx, group_id, body.user_id)


@router.delete(
    "/organizations/{org_id}/groups/{group_id}/members/{user_id}",
    tags=["groups"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_member(
    org_id: uuid.UUID,
    ctx: ManageGroups,
    session: DbSession,
    group_id: uuid.UUID,
    user_id: uuid.UUID,
) -> None:
    await groups.remove_member(session, ctx, group_id, user_id)
