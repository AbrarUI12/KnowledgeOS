"""Identity, organization and authorization tables (plan §7.2, §7.9 audit_events, §7.10).

Conventions (plan §7.1):
- UUIDv7 primary keys, timezone-aware timestamps;
- every tenant-scoped table carries `organization_id` explicitly (RLS policies: Session 08);
- status-like columns are text + CHECK constraints (easier to evolve than PostgreSQL enums);
- composite foreign keys (`..._id, organization_id`) make cross-tenant references impossible.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A person, identified by OIDC (issuer, sub). Global: not tenant-scoped."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("issuer", "external_subject"),
        CheckConstraint("status IN ('active', 'disabled')", name="status"),
        Index("ix_users_email_lower", text("lower(email)")),
    )

    issuer: Mapped[str] = mapped_column(Text)
    external_subject: Mapped[str] = mapped_column(Text)
    email: Mapped[str | None] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Organization(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant. The slug is for URLs only, never for authorization (plan §7.1)."""

    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug"),
        CheckConstraint("status IN ('active', 'suspended', 'deleted')", name="status"),
        CheckConstraint("slug ~ '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'", name="slug_format"),
    )

    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(63))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    settings_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named bundle of permissions. System roles have organization_id NULL and is_system true."""

    __tablename__ = "roles"
    __table_args__ = (
        # NULLS NOT DISTINCT: system role keys are unique too (PostgreSQL 15+).
        UniqueConstraint("organization_id", "key", postgresql_nulls_not_distinct=True),
        UniqueConstraint("id", "organization_id", name="uq_roles_id_organization_id"),
        CheckConstraint("key ~ '^[a-z][a-z0-9_]{1,62}$'", name="key_format"),
        CheckConstraint("is_system = (organization_id IS NULL)", name="system_roles_are_global"),
    )

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(63))
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    is_system: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))


class RolePermission(Base):
    __tablename__ = "role_permissions"
    __table_args__ = (
        CheckConstraint("permission ~ '^[a-z_]+\\.[a-z_]+$'", name="permission_format"),
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission: Mapped[str] = mapped_column(String(63), primary_key=True)
    # Denormalized for RLS (NULL for system roles, which are readable by everyone).
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )


class Membership(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("organization_id", "user_id"),
        CheckConstraint("status IN ('active', 'suspended')", name="status"),
        Index("ix_memberships_user_id", "user_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # System role (org NULL) or a custom role of the same org: checked by the service layer and
    # by the trg_memberships_role_scope trigger (migration 0002).
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Group(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("organization_id", "name"),
        UniqueConstraint("id", "organization_id", name="uq_groups_id_organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)


class GroupMembership(TimestampMixin, Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        # The group must belong to the same organization as the row.
        ForeignKeyConstraint(
            ["group_id", "organization_id"],
            ["groups.id", "groups.organization_id"],
            ondelete="CASCADE",
            name="fk_group_memberships_group_org",
        ),
        Index("ix_group_memberships_user_id", "user_id"),
    )

    group_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )


class AuditEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Append-only audit stream (plan §7.9). Never stores secrets or document content."""

    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("actor_type IN ('user', 'api_key', 'system')", name="actor_type"),
        Index("ix_audit_events_org_created", "organization_id", text("created_at DESC")),
        Index("ix_audit_events_org_action", "organization_id", "action"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    actor_type: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[uuid.UUID | None]
    action: Mapped[str] = mapped_column(String(100))
    resource_type: Mapped[str] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Scoped programmatic credentials. Only a hash of the secret is stored (plan §7.10)."""

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("prefix"),
        Index("ix_api_keys_organization_id", "organization_id"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text)
    prefix: Mapped[str] = mapped_column(String(32))
    secret_hash: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Invitation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Pending invitation; the token itself is never stored, only its hash."""

    __tablename__ = "invitations"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        Index("ix_invitations_org_email", "organization_id", text("lower(email)")),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    email: Mapped[str] = mapped_column(Text)
    role_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("roles.id", ondelete="CASCADE"))
    token_hash: Mapped[str] = mapped_column(Text)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
