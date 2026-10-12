"""Import every ORM model module here so Alembic autogenerate sees the full metadata."""

from app.db.models.identity import (
    ApiKey,
    AuditEvent,
    Group,
    GroupMembership,
    IdempotencyKey,
    Invitation,
    Membership,
    Organization,
    Role,
    RolePermission,
    User,
)

__all__ = [
    "ApiKey",
    "AuditEvent",
    "Group",
    "GroupMembership",
    "IdempotencyKey",
    "Invitation",
    "Membership",
    "Organization",
    "Role",
    "RolePermission",
    "User",
]
