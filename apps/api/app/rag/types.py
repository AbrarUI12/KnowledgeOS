"""Contract: retrieval and generation value types shared across RAG components (T1.0).

Flow: SearchBackend → `Candidate`s with per-branch ranks (`RankedHit`) → fusion (Cline T4.3) →
reranker (Codex T5.1) sets `rerank_score` → context packer (Codex T5.1) builds `EvidenceItem`s with
`SourceAlias`es → LLM gateway (Codex T5.2) → citation validator. All of these are DB-free; the
search backend (Claude T4.4) is the only component that touches the database, and it has already
applied the authorization predicate: nothing unauthorized ever becomes a `Candidate`.
"""

import uuid
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from app.ingestion.canonical import SHA256_PATTERN, SourceLocation


class Branch(StrEnum):
    DENSE = "dense"
    LEXICAL = "lexical"


class Candidate(BaseModel):
    """One authorized chunk returned by retrieval."""

    model_config = ConfigDict(frozen=True)

    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    ordinal: int
    title: str
    section_path: tuple[str, ...] = ()
    content: str
    content_hash: str = Field(pattern=SHA256_PATTERN)
    token_count: int
    location: SourceLocation = SourceLocation()
    version_number: int = 1
    source_url: str | None = None


class RankedHit(BaseModel):
    """A candidate with its rank/score in each branch and after fusion/reranking."""

    candidate: Candidate
    dense_rank: int | None = None  # 1-based; None = not returned by that branch
    dense_score: float | None = None  # cosine similarity
    lexical_rank: int | None = None
    lexical_score: float | None = None  # ts_rank_cd (+ boosts)
    fused_score: float | None = None
    rerank_score: float | None = None

    @property
    def chunk_id(self) -> uuid.UUID:
        return self.candidate.chunk_id


class SourceAlias(BaseModel):
    """Immutable per-answer alias `[S1]…` with metadata from storage, never from the model
    (§20.2)."""

    model_config = ConfigDict(frozen=True)

    alias: str = Field(pattern=r"^S[1-9][0-9]*$")
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    title: str
    version_number: int
    section_path: tuple[str, ...] = ()
    location: SourceLocation = SourceLocation()
    source_url: str | None = None
    content_hash: str = Field(pattern=SHA256_PATTERN)


class EvidenceItem(BaseModel):
    """A packed piece of evidence placed in the generation context."""

    source: SourceAlias
    content: str
    token_count: int
    rerank_score: float | None = None
    expanded_from: tuple[uuid.UUID, ...] = Field(
        default=(), description="Neighbor chunk IDs merged in by neighbor expansion"
    )


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    estimated: bool = False  # True when the provider didn't report usage


class DegradedFlags(BaseModel):
    """Explicit degradation markers (plan §3 principle 14)."""

    dense_unavailable: bool = False
    lexical_unavailable: bool = False
    rerank_bypassed: bool = False
    generation_fallback_model: str | None = None

    @property
    def any(self) -> bool:
        return (
            self.dense_unavailable
            or self.lexical_unavailable
            or self.rerank_bypassed
            or self.generation_fallback_model is not None
        )
