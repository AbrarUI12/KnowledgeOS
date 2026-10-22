"""Query runs and retrieval hits (S25-S26, plan §7.8). Mirrors migration 0011; tenant tables
with forced RLS."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, ForeignKeyConstraint, String, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin


def _org_fk() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("organizations.id", ondelete="CASCADE"))


class QueryRun(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "query_runs"

    organization_id: Mapped[uuid.UUID] = _org_fk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    knowledge_base_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID(as_uuid=True)))
    query_type: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), server_default="completed")
    query_hash: Mapped[str] = mapped_column(String(64))
    query_text: Mapped[str | None] = mapped_column(Text)
    query_language: Mapped[str | None] = mapped_column(String(16))
    filters_json: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    principal_summary: Mapped[str] = mapped_column(Text, server_default="")
    index_generations_json: Mapped[dict[str, str]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    embedding_model: Mapped[str | None] = mapped_column(Text)
    rag_profile_version: Mapped[str | None] = mapped_column(Text)
    reranker_model: Mapped[str | None] = mapped_column(Text)
    generation_model: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[uuid.UUID | None]
    trace_id: Mapped[str | None] = mapped_column(Text)
    degraded: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    retrieval_latency_ms: Mapped[float | None] = mapped_column(Float)
    rerank_latency_ms: Mapped[float | None] = mapped_column(Float)
    generation_latency_ms: Mapped[float | None] = mapped_column(Float)
    total_latency_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class RetrievalHit(Base):
    __tablename__ = "retrieval_hits"
    __table_args__ = (
        ForeignKeyConstraint(
            ["query_run_id", "organization_id"],
            ["query_runs.id", "query_runs.organization_id"],
            ondelete="CASCADE",
        ),
    )

    query_run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    chunk_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    organization_id: Mapped[uuid.UUID] = _org_fk()
    document_id: Mapped[uuid.UUID]
    knowledge_base_id: Mapped[uuid.UUID]
    rank: Mapped[int | None]
    dense_rank: Mapped[int | None]
    dense_score: Mapped[float | None] = mapped_column(Float)
    lexical_rank: Mapped[int | None]
    lexical_score: Mapped[float | None] = mapped_column(Float)
    fusion_score: Mapped[float | None] = mapped_column(Float)
    rerank_score: Mapped[float | None] = mapped_column(Float)
    selected_for_context: Mapped[bool] = mapped_column(server_default="false")


class RagProfile(UUIDPrimaryKeyMixin, Base):
    """Immutable versioned profile (migration 0012); `organization_id` None = system preset."""

    __tablename__ = "rag_profiles"

    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(64))
    version: Mapped[int]
    config_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class ModelPolicy(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "model_policies"

    organization_id: Mapped[uuid.UUID] = _org_fk()
    knowledge_base_id: Mapped[uuid.UUID | None]
    local_only: Mapped[bool] = mapped_column(server_default="false")
    allowed_providers_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    max_external_classification: Mapped[str] = mapped_column(String(16), server_default="internal")
    generation_models: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    reranker_model: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Answer(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "answers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["query_run_id", "organization_id"],
            ["query_runs.id", "query_runs.organization_id"],
            ondelete="CASCADE",
        ),
    )

    organization_id: Mapped[uuid.UUID] = _org_fk()
    query_run_id: Mapped[uuid.UUID]
    answer_markdown: Mapped[str | None] = mapped_column(Text)
    abstained: Mapped[bool] = mapped_column(server_default="false")
    abstain_reason: Mapped[str | None] = mapped_column(String(64))
    evidence_status: Mapped[str | None] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(Text)
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    usage_estimated: Mapped[bool] = mapped_column(server_default="false")
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["answer_id", "organization_id"],
            ["answers.id", "answers.organization_id"],
            ondelete="CASCADE",
        ),
    )

    answer_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    source_alias: Mapped[str] = mapped_column(String(8), primary_key=True)
    organization_id: Mapped[uuid.UUID] = _org_fk()
    chunk_id: Mapped[uuid.UUID]
    document_version_id: Mapped[uuid.UUID]
    page_start: Mapped[int | None]
    page_end: Mapped[int | None]
    valid: Mapped[bool] = mapped_column(server_default="true")
