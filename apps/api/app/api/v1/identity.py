"""Identity & organization endpoints (contracts from T1.0; implemented in T1.1 and T1.3)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dependencies.auth import CurrentUser
from app.api.v1._stub import ERRORS, IdempotencyKeyHeader, stub
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
from app.services.users import load_me

router = APIRouter(responses=ERRORS)

Cursor = Annotated[str | None, Query(description="Opaque cursor from a previous page")]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("/me", tags=["me"], response_model=MeResponse)
async def get_me(user: CurrentUser, session: DbSession) -> MeResponse:
    """The authenticated user and their organization memberships with effective permissions."""
    return await load_me(session, user)


@router.get("/organizations", tags=["organizations"], response_model=list[OrganizationOut])
async def list_organizations() -> list[OrganizationOut]:
    """Organizations the caller is an active member of."""
    stub("T1.3")


@router.post(
    "/organizations",
    tags=["organizations"],
    response_model=OrganizationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_organization(
    body: OrganizationCreate, idempotency_key: IdempotencyKeyHeader = None
) -> OrganizationOut:
    """Create an organization; the caller becomes its owner. Supports `Idempotency-Key`."""
    stub("T1.3")


@router.get("/organizations/{org_id}/members", tags=["members"], response_model=Page[MemberOut])
async def list_members(
    org_id: uuid.UUID, cursor: Cursor = None, limit: Limit = 50
) -> Page[MemberOut]:
    stub("T1.3")


@router.patch(
    "/organizations/{org_id}/members/{user_id}", tags=["members"], response_model=MemberOut
)
async def update_member(org_id: uuid.UUID, user_id: uuid.UUID, body: MemberUpdate) -> MemberOut:
    """Change a member's role (`members.manage`). The last owner can't be demoted (409)."""
    stub("T1.3")


@router.delete(
    "/organizations/{org_id}/members/{user_id}",
    tags=["members"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(org_id: uuid.UUID, user_id: uuid.UUID) -> None:
    stub("T1.3")


@router.post(
    "/organizations/{org_id}/invitations",
    tags=["invitations"],
    response_model=InvitationOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_invitation(org_id: uuid.UUID, body: InvitationCreate) -> InvitationOut:
    """Invite by email; returns a one-time `accept_url` (the token is stored hashed)."""
    stub("T1.3")


@router.post("/invitations/{token}/accept", tags=["invitations"], response_model=InvitationAccepted)
async def accept_invitation(token: str) -> InvitationAccepted:
    stub("T1.3")


@router.get("/organizations/{org_id}/groups", tags=["groups"], response_model=Page[GroupOut])
async def list_groups(
    org_id: uuid.UUID, cursor: Cursor = None, limit: Limit = 50
) -> Page[GroupOut]:
    stub("T1.3")


@router.post(
    "/organizations/{org_id}/groups",
    tags=["groups"],
    response_model=GroupOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_group(org_id: uuid.UUID, body: GroupCreate) -> GroupOut:
    stub("T1.3")


@router.patch("/organizations/{org_id}/groups/{group_id}", tags=["groups"], response_model=GroupOut)
async def update_group(org_id: uuid.UUID, group_id: uuid.UUID, body: GroupUpdate) -> GroupOut:
    stub("T1.3")


@router.delete(
    "/organizations/{org_id}/groups/{group_id}",
    tags=["groups"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_group(org_id: uuid.UUID, group_id: uuid.UUID) -> None:
    stub("T1.3")


@router.get(
    "/organizations/{org_id}/groups/{group_id}/members",
    tags=["groups"],
    response_model=Page[MemberOut],
)
async def list_group_members(
    org_id: uuid.UUID, group_id: uuid.UUID, cursor: Cursor = None, limit: Limit = 50
) -> Page[MemberOut]:
    stub("T1.3")


@router.post(
    "/organizations/{org_id}/groups/{group_id}/members",
    tags=["groups"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def add_group_member(org_id: uuid.UUID, group_id: uuid.UUID, body: GroupMemberAdd) -> None:
    stub("T1.3")


@router.delete(
    "/organizations/{org_id}/groups/{group_id}/members/{user_id}",
    tags=["groups"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_group_member(org_id: uuid.UUID, group_id: uuid.UUID, user_id: uuid.UUID) -> None:
    stub("T1.3")
