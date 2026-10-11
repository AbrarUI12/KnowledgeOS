"""Contract: retrieval backend (ADR-002, plan §8.3, §17, §18, T1.0). Implementation: Claude T4.4.

Authorization is part of the request type, not an option: `SearchScope` is required and the backend
must apply organization, KB, active index generation, active document version, not-deleted and
`access_principals` filters **inside** the query, before ranking (never post-filtering).
"""

import uuid
from datetime import date
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.rag.types import DegradedFlags, RankedHit


class SearchScope(BaseModel):
    """Who is searching and where. Built by the server from the authenticated context only."""

    model_config = ConfigDict(frozen=True)

    organization_id: uuid.UUID
    knowledge_base_ids: tuple[uuid.UUID, ...] = Field(min_length=1)
    principal_tokens: tuple[str, ...] = Field(
        min_length=1, description="e.g. 'user:<id>', 'group:<id>', 'role:member', 'org:<id>'"
    )


class QueryFilters(BaseModel):
    """Whitelisted, typed filters (plan §17). Never raw SQL; LLM-derived values are only hints."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_ids: tuple[uuid.UUID, ...] = ()
    source_ids: tuple[uuid.UUID, ...] = ()
    document_types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    department: str | None = None
    modified_from: date | None = None
    modified_to: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    languages: tuple[str, ...] = ()


class HybridSearchRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: SearchScope
    query: str = Field(min_length=1, max_length=4000)
    filters: QueryFilters = QueryFilters()
    query_embedding: tuple[float, ...] | None = Field(
        default=None,
        description="Pre-computed with the active generation's model; None = lexical only",
    )
    dense_k: int = Field(default=50, ge=1, le=500)
    lexical_k: int = Field(default=50, ge=1, le=500)
    allow_degraded: bool = True


class BranchTiming(BaseModel):
    dense_ms: float | None = None
    lexical_ms: float | None = None


class HybridSearchResult(BaseModel):
    """Per-branch ranked hits, unfused. Fusion (app/rag/fusion) runs on top of this."""

    dense: list[RankedHit] = Field(default_factory=list)
    lexical: list[RankedHit] = Field(default_factory=list)
    index_generation_id: uuid.UUID
    degraded: DegradedFlags = DegradedFlags()
    timing: BranchTiming = BranchTiming()


@runtime_checkable
class SearchBackend(Protocol):
    async def hybrid_search(self, request: HybridSearchRequest) -> HybridSearchResult: ...

    async def neighbors(
        self, scope: SearchScope, chunk_id: uuid.UUID, *, before: int = 1, after: int = 1
    ) -> list[RankedHit]:
        """Adjacent chunks of the same version/generation, with the same authorization applied.
        Used by context packing for neighbor expansion (plan §20.1)."""
        ...
