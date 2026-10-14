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
