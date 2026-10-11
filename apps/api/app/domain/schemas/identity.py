"""API schemas: current user, organizations, members, invitations, groups (T1.0; implemented
T1.1/T1.3)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.auth.permissions import Permission

SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
ROLE_KEY_PATTERN = r"^[a-z][a-z0-9_]{1,62}$"


class UserOut(BaseModel):
    id: uuid.UUID
    email: str | None
    display_name: str | None


class MembershipOut(BaseModel):
    organization_id: uuid.UUID
    organization_name: str
    organization_slug: str
    role: str = Field(description="Role key, e.g. 'owner', 'member'")
    permissions: list[Permission]


class MeResponse(BaseModel):
    user: UserOut
    memberships: list[MembershipOut]


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(pattern=SLUG_PATTERN)


class OrganizationOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime


class MemberOut(BaseModel):
    user_id: uuid.UUID
    email: str | None
    display_name: str | None
    role: str
    status: str
    group_ids: list[uuid.UUID] = Field(default_factory=list)
    joined_at: datetime
    last_seen_at: datetime | None


class MemberUpdate(BaseModel):
    role: str = Field(pattern=ROLE_KEY_PATTERN)


class InvitationCreate(BaseModel):
    email: EmailStr
    role: str = Field(default="member", pattern=ROLE_KEY_PATTERN)


class InvitationOut(BaseModel):
    id: uuid.UUID
    email: str
    role: str
    expires_at: datetime
    accept_url: str | None = Field(
        default=None, description="Only returned once, on creation (the token isn't stored)"
    )


class InvitationAccepted(BaseModel):
    organization_id: uuid.UUID
    role: str


class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    member_count: int
    created_at: datetime


class GroupMemberAdd(BaseModel):
    user_id: uuid.UUID
