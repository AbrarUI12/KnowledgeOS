"""RAG profiles (S27, plan §7.7): immutable, versioned retrieval and generation settings.

A KB uses its `active_rag_profile_version_id`, or the newest system `default-hybrid` version when
it has none. Editing a profile inserts the next version (the database denies the runtime role any
UPDATE or DELETE on `rag_profiles`), so every query run can name exactly the settings it used.
"""

import uuid
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import NotFound
from app.auth.authorization import RequestContext
from app.db.base import new_uuid
from app.db.models import KnowledgeBase, RagProfile
from app.rag.context.packer import PackingConfig
from app.rag.fusion.rrf import FusionConfig

SYSTEM_DEFAULT = "default-hybrid"


class RagProfileConfig(BaseModel):
    """The settings one profile version pins (S27 `default-hybrid-v1` defaults)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dense_k: int = Field(default=50, ge=1, le=500)
    lexical_k: int = Field(default=50, ge=1, le=500)
    rrf_k0: float = Field(default=60, gt=0)
    dense_weight: float = Field(default=0.55, ge=0)
    lexical_weight: float = Field(default=0.45, ge=0)
    max_per_document: int = Field(default=3, ge=1)
    rerank_candidates: int = Field(default=30, ge=1, le=100)
    rerank_timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    allow_degraded_rerank: bool = True
    final_context_k: int = Field(default=8, ge=1, le=50)
    max_context_tokens: int = Field(default=4500, ge=256)
    per_document_cap: int = Field(default=3, ge=1)
    query_rewrite: bool = False
    query_decomposition: bool = False
    abstain_min_rerank_score: float = 0.0  # placeholder until calibrated (Session 41)
    prompt_version: str = "grounded_answer/v1"

    def fusion(self) -> FusionConfig:
        return FusionConfig(
            k0=self.rrf_k0,
            dense_weight=self.dense_weight,
            lexical_weight=self.lexical_weight,
            max_per_document=self.max_per_document,
        )

    def packing(self) -> PackingConfig:
        return PackingConfig(
            max_tokens=self.max_context_tokens,
            max_items=self.final_context_k,
            per_document_cap=self.per_document_cap,
        )


@dataclass(frozen=True, slots=True)
class ActiveProfile:
    id: uuid.UUID
    name: str
    version: int
    config: RagProfileConfig

    @property
    def label(self) -> str:
        return f"{self.name}-v{self.version}"


def _active(row: RagProfile) -> ActiveProfile:
    return ActiveProfile(row.id, row.name, row.version, RagProfileConfig(**row.config_json))


async def _system_default(session: AsyncSession) -> RagProfile:
    row = await session.scalar(
        select(RagProfile)
        .where(RagProfile.organization_id.is_(None), RagProfile.name == SYSTEM_DEFAULT)
        .order_by(RagProfile.version.desc())
        .limit(1)
    )
    if row is None:  # seeded by migration 0012; missing means a broken deployment
        raise RuntimeError("the system RAG profile is missing")
    return row


async def default_profile(session: AsyncSession) -> ActiveProfile:
    return _active(await _system_default(session))


async def active_profile(session: AsyncSession, kb: KnowledgeBase) -> ActiveProfile:
    if kb.active_rag_profile_version_id is not None:
        row = await session.scalar(
            select(RagProfile).where(
                RagProfile.id == kb.active_rag_profile_version_id,
                or_(
                    RagProfile.organization_id.is_(None),
                    RagProfile.organization_id == kb.organization_id,
                ),
            )
        )
        if row is not None:
            return _active(row)
    return _active(await _system_default(session))


async def create_version(
    session: AsyncSession, ctx: RequestContext, name: str, config: RagProfileConfig
) -> ActiveProfile:
    """Insert the next version of the organization's profile `name` (versions never change)."""
    # Serialize version numbering per (org, name) for the rest of the transaction.
    await session.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(f"rag:{ctx.organization_id}:{name}", 0)
            )
        )
    )
    latest = await session.scalar(
        select(func.max(RagProfile.version)).where(
            RagProfile.organization_id == ctx.organization_id, RagProfile.name == name
        )
    )
    row = RagProfile(
        id=new_uuid(),
        organization_id=ctx.organization_id,
        name=name,
        version=(latest or 0) + 1,
        config_json=config.model_dump(mode="json"),
        created_by=ctx.user_id,
    )
    session.add(row)
    await session.flush()
    return _active(row)


async def activate(
    session: AsyncSession, ctx: RequestContext, kb: KnowledgeBase, profile_id: uuid.UUID
) -> ActiveProfile:
    """Point the KB at a profile version: a system preset or one of its own organization's."""
    row = await session.scalar(
        select(RagProfile).where(
            RagProfile.id == profile_id,
            or_(
                RagProfile.organization_id.is_(None),
                RagProfile.organization_id == ctx.organization_id,
            ),
        )
    )
    if row is None:
        raise NotFound("The RAG profile was not found.")
    kb.active_rag_profile_version_id = row.id
    await session.flush()
    return _active(row)
