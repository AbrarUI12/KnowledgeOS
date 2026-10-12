"""Knowledge bases, sources, documents, versions, ACLs, uploads, ingestion jobs and the outbox
(S12, plan §7.3-§7.5). Mirrors migration 0005; every table is tenant-scoped with forced RLS."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))


class KnowledgeBase(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "knowledge_bases"

    organization_id: Mapped[uuid.UUID] = _org_fk()
    name: Mapped[str] = mapped_column(Text)
    slug: Mapped[str] = mapped_column(String(63))
    description: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(16), server_default="organization")
    active_index_generation_id: Mapped[uuid.UUID | None]
    active_rag_profile_version_id: Mapped[uuid.UUID | None]
    model_policy_id: Mapped[uuid.UUID | None]
    retention_policy_id: Mapped[uuid.UUID | None]
    acl_propagated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class _AclMixin:
    organization_id: Mapped[uuid.UUID] = _org_fk()
    principal_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    principal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    permission: Mapped[str] = mapped_column(String(16), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class KnowledgeBaseAcl(_AclMixin, Base):
    __tablename__ = "knowledge_base_acl"
    __table_args__ = (
        ForeignKeyConstraint(
            ["knowledge_base_id", "organization_id"],
            ["knowledge_bases.id", "knowledge_bases.organization_id"],
            ondelete="CASCADE",
        ),
    )

    knowledge_base_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class DataSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "data_sources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["knowledge_base_id", "organization_id"],
            ["knowledge_bases.id", "knowledge_bases.organization_id"],
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    knowledge_base_id: Mapped[uuid.UUID]
    type: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    trust_level: Mapped[str] = mapped_column(String(16), server_default="internal")
    permission_sync_mode: Mapped[str] = mapped_column(String(16), server_default="none")
    encrypted_config_ref: Mapped[str | None] = mapped_column(Text)
    sync_cursor: Mapped[str | None] = mapped_column(Text)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(32))
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class Document(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["knowledge_base_id", "organization_id"],
            ["knowledge_bases.id", "knowledge_bases.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["data_sources.id", "data_sources.organization_id"],
            ondelete="RESTRICT",
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    knowledge_base_id: Mapped[uuid.UUID]
    source_id: Mapped[uuid.UUID]
    canonical_key: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    document_type: Mapped[str | None] = mapped_column(String(64))
    classification: Mapped[str] = mapped_column(String(16), server_default="internal")
    status: Mapped[str] = mapped_column(String(16), server_default="active")
    active_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id", ondelete="SET NULL", use_alter=True)
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentVersion(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["documents.id", "documents.organization_id"],
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    document_id: Mapped[uuid.UUID]
    version_number: Mapped[int]
    sha256: Mapped[str | None] = mapped_column(String(64))
    object_key: Mapped[str | None] = mapped_column(Text)
    canonical_artifact_key: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parser_name: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[str | None] = mapped_column(Text)
    integrity_status: Mapped[str] = mapped_column(String(16), server_default="pending")
    approval_status: Mapped[str] = mapped_column(String(16), server_default="not_required")
    ingestion_status: Mapped[str] = mapped_column(String(32), server_default="RECEIVED")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )


class SourceObject(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "source_objects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["source_id", "organization_id"],
            ["data_sources.id", "data_sources.organization_id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["documents.id", "documents.organization_id"],
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    source_id: Mapped[uuid.UUID]
    external_id: Mapped[str] = mapped_column(Text)
    external_revision: Mapped[str | None] = mapped_column(Text)
    document_id: Mapped[uuid.UUID | None]
    source_url: Mapped[str | None] = mapped_column(Text)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DocumentAcl(_AclMixin, Base):
    __tablename__ = "document_acl"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["documents.id", "documents.organization_id"],
            ondelete="CASCADE",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)


class Upload(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "uploads"
    __table_args__ = (
        ForeignKeyConstraint(
            ["knowledge_base_id", "organization_id"],
            ["knowledge_bases.id", "knowledge_bases.organization_id"],
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    knowledge_base_id: Mapped[uuid.UUID]
    document_id: Mapped[uuid.UUID | None]
    document_version_id: Mapped[uuid.UUID | None]
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    filename: Mapped[str] = mapped_column(Text)
    declared_mime: Mapped[str] = mapped_column(Text)
    declared_size: Mapped[int] = mapped_column(BigInteger)
    object_key: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), server_default="pending")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IngestionJob(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_jobs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_version_id", "organization_id"],
            ["document_versions.id", "document_versions.organization_id"],
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    document_version_id: Mapped[uuid.UUID]
    index_generation_id: Mapped[uuid.UUID | None]
    state: Mapped[str] = mapped_column(String(32), server_default="RECEIVED")
    stage: Mapped[str | None] = mapped_column(String(32))
    progress_percent: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    attempt_count: Mapped[int] = mapped_column(server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(64))
    error_detail_safe: Mapped[str | None] = mapped_column(Text)
    stage_checkpoints: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    lease_owner: Mapped[str | None] = mapped_column(Text)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OutboxEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Written in the same transaction as the business change (ADR-005); the dispatcher
    publishes it (Session 16)."""

    __tablename__ = "outbox_events"

    organization_id: Mapped[uuid.UUID] = _org_fk()
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_type: Mapped[str] = mapped_column(String(64))
    aggregate_id: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text)
