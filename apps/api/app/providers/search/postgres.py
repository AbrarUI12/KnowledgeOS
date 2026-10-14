"""Permission-aware hybrid search on PostgreSQL + pgvector (ADR-002, plan §8.3-§8.4, §18; T4.4).

Every query starts from `_scoped()`, the single place that applies tenancy and authorization:
organization, the allowed KBs (not archived), each KB's active index generation, each document's
active version (not archived or deleted), child chunks that are visible, and
`access_principals && caller tokens`. Those are WHERE clauses of the same SQL that ranks, so
nothing unauthorized is ever scored, let alone returned (no post-filtering). Each branch runs in
its own transaction with the tenant context set, so RLS applies underneath as well.

- Dense: HNSW cosine search with iterative scanning (pgvector ≥ 0.8), which keeps scanning until
  `k` rows survive the filters, in a materialized CTE, re-sorted by distance (relaxed order can
  return rows slightly out of order). Only chunks embedded by the request's model are compared.
- Lexical: `websearch_to_tsquery` per text-search configuration (each chunk was indexed with the
  configuration of its detected language), `ts_rank_cd` over title A / section B / body C, an
  exact-identifier boost (`HR-142-B`), and a title-trigram fallback when full text finds too little.
- Hybrid: both branches concurrently on two connections; one failing branch degrades with flags
  when the request allows it (plan §25.2). Fusion runs on top (`app.rag.fusion`).
"""

import asyncio
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar

from sqlalchemy import (
    ColumnElement,
    Float,
    Select,
    Text,
    and_,
    case,
    cast,
    false,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.dialects.postgresql import ARRAY, REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Chunk, Document, DocumentVersion, IndexGeneration, KnowledgeBase
from app.db.tenant import tenant_session
from app.db.text_search import SEARCH_CONFIGS, fts_config
from app.db.types import Vector
from app.domain.enums import DocumentStatus
from app.ingestion.canonical import SourceLocation
from app.providers.search.base import (
    BranchTiming,
    HybridSearchRequest,
    HybridSearchResult,
    QueryFilters,
    SearchScope,
)
from app.rag.types import Candidate, DegradedFlags, RankedHit

T = TypeVar("T")

# Same shape as the chunker's identifiers (T3.4), matched case-insensitively in queries.
_IDENTIFIER = re.compile(r"\b[A-Z]{2,}(?:-\d+)+(?:-[A-Z0-9]+)*\b", re.IGNORECASE)


class UnsupportedFilter(ValueError):
    """A QueryFilters field with no indexed metadata behind it yet (never silently ignored)."""


@dataclass(frozen=True, slots=True)
class SearchTuning:
    ef_search: int = 100
    max_scan_tuples: int = 20_000
    statement_timeout_ms: int = 5_000
    identifier_boost: float = 1.0
    trigram_min_results: int = 3
    trigram_threshold: float = 0.3
    trigram_weight: float = 0.5
    # Extra transaction-local planner settings, e.g. (("enable_seqscan", "off"),) to make
    # benchmarks measure the HNSW path on corpora small enough that an exact scan wins. Empty in
    # production: there the planner picks exact search exactly when it's cheaper.
    planner_settings: tuple[tuple[str, str], ...] = ()


def query_identifiers(query: str) -> list[str]:
    return sorted({match.upper() for match in _IDENTIFIER.findall(query)})


def _candidate_columns() -> tuple[Any, ...]:
    return (
        Chunk.id,
        Chunk.document_id,
        Chunk.document_version_id,
        Chunk.knowledge_base_id,
        Chunk.ordinal,
        Document.title,
        Chunk.section_path,
        Chunk.content,
        Chunk.content_hash,
        Chunk.token_count,
        Chunk.location_json,
        DocumentVersion.version_number,
    )


def _candidate(row: Any) -> Candidate:
    return Candidate(
        chunk_id=row.id,
        document_id=row.document_id,
        document_version_id=row.document_version_id,
        knowledge_base_id=row.knowledge_base_id,
        ordinal=row.ordinal,
        title=row.title,
        section_path=tuple(row.section_path),
        content=row.content,
        content_hash=row.content_hash,
        token_count=row.token_count,
        location=SourceLocation.model_validate(row.location_json or {}),
        version_number=row.version_number,
    )


def authorization_predicate(scope: SearchScope) -> list[ColumnElement[bool]]:
    """Every condition a chunk must meet to be searchable by `scope` (plan §8.4), expressed on
    `chunks` alone (semi-joins for the KB and document checks), so each branch stays a single-table
    scan that the HNSW/GIN indexes can drive and filter as they go. Used by every query of this
    backend through `_scoped`; there is no other way to read chunk rows here."""
    kbs = scope.knowledge_base_ids
    active_generations = select(KnowledgeBase.active_index_generation_id).where(
        KnowledgeBase.id.in_(kbs),
        KnowledgeBase.organization_id == scope.organization_id,
        KnowledgeBase.archived_at.is_(None),
        KnowledgeBase.active_index_generation_id.is_not(None),
    )
    active_versions = select(Document.active_version_id).where(
        Document.knowledge_base_id.in_(kbs),
        Document.organization_id == scope.organization_id,
        Document.status == DocumentStatus.ACTIVE.value,
        Document.archived_at.is_(None),
        Document.active_version_id.is_not(None),
    )
    return [
        Chunk.organization_id == scope.organization_id,
        Chunk.knowledge_base_id.in_(kbs),
        Chunk.index_generation_id.in_(active_generations),
        Chunk.document_version_id.in_(active_versions),
        Chunk.is_parent.is_(False),
        Chunk.visibility == "visible",
        Chunk.access_principals.overlap(cast(list(scope.principal_tokens), ARRAY(Text))),
    ]


def _with_columns(query: Select[Any]) -> Select[Any]:
    """Join the document and version for candidate columns (never for authorization)."""
    return query.join(Document, Document.id == Chunk.document_id).join(
        DocumentVersion, DocumentVersion.id == Chunk.document_version_id
    )


def _scoped(scope: SearchScope, *columns: Any) -> Select[Any]:
    return _with_columns(select(*columns).select_from(Chunk)).where(*authorization_predicate(scope))


def compile_filters(filters: QueryFilters) -> list[ColumnElement[bool]]:
    """Whitelisted, typed filters → SQL on `chunks` (plan §17). They only ever narrow the
    authorized pool."""
    if filters.tags or filters.department is not None:
        raise UnsupportedFilter("tags and department filters aren't indexed yet")
    clauses: list[ColumnElement[bool]] = []
    if filters.document_ids:
        clauses.append(Chunk.document_id.in_(filters.document_ids))
    documents: list[ColumnElement[bool]] = []
    if filters.source_ids:
        documents.append(Document.source_id.in_(filters.source_ids))
    if filters.document_types:
        documents.append(Document.document_type.in_(filters.document_types))
    if documents:
        clauses.append(Chunk.document_id.in_(select(Document.id).where(*documents)))
    if filters.languages:
        configs = sorted({fts_config(language) for language in filters.languages})
        clauses.append(cast(Chunk.fts_config, Text).in_(configs))
    versions: list[ColumnElement[bool]] = []
    modified = func.coalesce(DocumentVersion.source_modified_at, DocumentVersion.created_at)
    if filters.modified_from:
        versions.append(func.date(modified) >= filters.modified_from)
    if filters.modified_to:
        versions.append(func.date(modified) <= filters.modified_to)
    # Effective periods overlap the requested window (open ends always overlap).
    if filters.effective_from:
        versions.append(
            or_(
                DocumentVersion.effective_to.is_(None),
                func.date(DocumentVersion.effective_to) >= filters.effective_from,
            )
        )
    if filters.effective_to:
        versions.append(
            or_(
                DocumentVersion.effective_from.is_(None),
                func.date(DocumentVersion.effective_from) <= filters.effective_to,
            )
        )
    if versions:
        clauses.append(Chunk.document_version_id.in_(select(DocumentVersion.id).where(*versions)))
    return clauses


class PostgresSearchBackend:
    def __init__(
        self,
        sessionmaker: async_sessionmaker[AsyncSession],
        tuning: SearchTuning | None = None,
    ) -> None:
        self._sessionmaker = sessionmaker
        self.tuning = tuning or SearchTuning()

    async def _in_tenant(
        self, scope: SearchScope, work: Callable[[AsyncSession], Awaitable[T]]
    ) -> T:
        async with tenant_session(self._sessionmaker, scope.organization_id) as session:
            settings = (
                ("statement_timeout", str(self.tuning.statement_timeout_ms)),
                *self.tuning.planner_settings,
            )
            for name, value in settings:
                await session.execute(select(func.set_config(name, value, True)))
            return await work(session)

    # ------------------------------------------------------------------------- dense

    async def dense_search(self, request: HybridSearchRequest) -> list[RankedHit]:
        if request.query_embedding is None:
            return []
        return await self._in_tenant(request.scope, lambda s: self._dense(s, request))

    async def _dense(self, session: AsyncSession, request: HybridSearchRequest) -> list[RankedHit]:
        assert request.query_embedding is not None  # noqa: S101 (checked by the caller)
        tuning = self.tuning
        for name, value in (
            ("hnsw.ef_search", str(tuning.ef_search)),
            ("hnsw.iterative_scan", "relaxed_order"),
            ("hnsw.max_scan_tuples", str(tuning.max_scan_tuples)),
        ):
            await session.execute(select(func.set_config(name, value, True)))
        dimension = len(request.query_embedding)
        query = literal(list(request.query_embedding), type_=Vector(dimension))
        distance = Chunk.embedding.op("<=>", return_type=Float)(query)
        same_model = select(IndexGeneration.id).where(
            IndexGeneration.embedding_model == request.embedding_model,
            IndexGeneration.embedding_dimension == dimension,
        )
        nearest = (
            select(Chunk.id.label("chunk_id"), distance.label("distance"))
            .where(
                *authorization_predicate(request.scope),
                Chunk.embedding.is_not(None),
                Chunk.index_generation_id.in_(same_model),
                *compile_filters(request.filters),
            )
            .order_by(distance)
            .limit(request.dense_k)
            .cte("nearest")
            .prefix_with("MATERIALIZED")
        )
        rows = (
            await session.execute(
                select(*_candidate_columns(), nearest.c.distance)
                .select_from(nearest)
                .join(Chunk, Chunk.id == nearest.c.chunk_id)
                .join(Document, Document.id == Chunk.document_id)
                .join(DocumentVersion, DocumentVersion.id == Chunk.document_version_id)
                .order_by(nearest.c.distance, Chunk.id)  # relaxed_order → re-sort
            )
        ).all()
        return [
            RankedHit(candidate=_candidate(row), dense_rank=rank, dense_score=1 - row.distance)
            for rank, row in enumerate(rows, 1)
        ]

    # ------------------------------------------------------------------------- lexical

    async def lexical_search(self, request: HybridSearchRequest) -> list[RankedHit]:
        return await self._in_tenant(request.scope, lambda s: self._lexical(s, request))

    async def _lexical(
        self, session: AsyncSession, request: HybridSearchRequest
    ) -> list[RankedHit]:
        tuning = self.tuning
        text = request.query
        filters = compile_filters(request.filters)

        def tsquery(config: Any) -> Any:
            return func.websearch_to_tsquery(config, text)

        # One constant tsquery per configuration, so each branch can use the GIN index.
        full_text = or_(
            *(
                and_(
                    cast(Chunk.fts_config, Text) == config,
                    Chunk.search_vector.op("@@")(tsquery(cast(literal(config), REGCONFIG))),
                )
                for config in SEARCH_CONFIGS
            )
        )
        identifiers = query_identifiers(text)
        exact = (
            Chunk.identifiers.overlap(cast(identifiers, ARRAY(Text))) if identifiers else false()
        )
        score = func.coalesce(
            func.ts_rank_cd(Chunk.search_vector, tsquery(Chunk.fts_config), 32), 0.0
        ) + case((exact, tuning.identifier_boost), else_=0.0)
        rows = (
            await session.execute(
                _scoped(request.scope, *_candidate_columns(), score.label("score"))
                .where(or_(full_text, exact), *filters)
                .order_by(score.desc(), Chunk.id)
                .limit(request.lexical_k)
            )
        ).all()
        hits = [(row, float(row.score)) for row in rows]

        # Title-trigram fallback for misspelled or partial titles, still fully authorized.
        missing = min(request.lexical_k, tuning.trigram_min_results) - len(hits)
        if missing > 0:
            seen = [row.id for row, _ in hits]
            similarity = func.similarity(Document.title, text)
            fallback = (
                await session.execute(
                    _scoped(request.scope, *_candidate_columns(), similarity.label("score"))
                    .where(
                        similarity >= tuning.trigram_threshold,
                        Chunk.id.not_in(seen) if seen else literal(True),
                        *filters,
                    )
                    .order_by(similarity.desc(), Chunk.ordinal, Chunk.id)
                    .limit(request.lexical_k - len(hits))
                )
            ).all()
            hits += [(row, float(row.score) * tuning.trigram_weight) for row in fallback]
        return [
            RankedHit(candidate=_candidate(row), lexical_rank=rank, lexical_score=value)
            for rank, (row, value) in enumerate(hits, 1)
        ]

    # ------------------------------------------------------------------------- hybrid

    async def _generations(self, scope: SearchScope) -> dict[uuid.UUID, uuid.UUID]:
        async def load(session: AsyncSession) -> dict[uuid.UUID, uuid.UUID]:
            rows = await session.execute(
                select(KnowledgeBase.id, KnowledgeBase.active_index_generation_id).where(
                    KnowledgeBase.id.in_(scope.knowledge_base_ids),
                    KnowledgeBase.archived_at.is_(None),
                    KnowledgeBase.active_index_generation_id.is_not(None),
                )
            )
            return {kb: generation for kb, generation in rows.all() if generation is not None}

        return await self._in_tenant(scope, load)

    async def hybrid_search(self, request: HybridSearchRequest) -> HybridSearchResult:
        async def timed(branch: Awaitable[list[RankedHit]]) -> tuple[list[RankedHit], float]:
            started = time.perf_counter()
            hits = await branch
            return hits, (time.perf_counter() - started) * 1000

        dense, lexical, generations = await asyncio.gather(
            timed(self.dense_search(request)),
            timed(self.lexical_search(request)),
            self._generations(request.scope),
            return_exceptions=True,
        )
        if isinstance(generations, BaseException):
            raise generations
        failures = [r for r in (dense, lexical) if isinstance(r, BaseException)]
        if len(failures) == 2 or (failures and not request.allow_degraded):
            raise failures[0]
        for failure in failures:  # a filter the backend can't apply is the caller's error
            if isinstance(failure, UnsupportedFilter):
                raise failure
        dense_hits, dense_ms = ([], None) if isinstance(dense, BaseException) else dense
        lexical_hits, lexical_ms = ([], None) if isinstance(lexical, BaseException) else lexical
        return HybridSearchResult(
            dense=dense_hits,
            lexical=lexical_hits,
            index_generation_ids=generations,
            degraded=DegradedFlags(
                dense_unavailable=isinstance(dense, BaseException),
                lexical_unavailable=isinstance(lexical, BaseException),
            ),
            timing=BranchTiming(dense_ms=dense_ms, lexical_ms=lexical_ms),
        )

    # ------------------------------------------------------------------------- context

    async def neighbors(
        self, scope: SearchScope, chunk_id: uuid.UUID, *, before: int = 1, after: int = 1
    ) -> list[RankedHit]:
        """The authorized child chunks right before and after `chunk_id` in its version and
        generation (context expansion, plan §20.1). Empty if the chunk itself isn't readable."""

        async def load(session: AsyncSession) -> list[RankedHit]:
            target = (
                await session.execute(
                    _scoped(
                        scope,
                        Chunk.document_version_id,
                        Chunk.index_generation_id,
                        Chunk.ordinal,
                    ).where(Chunk.id == chunk_id)
                )
            ).one_or_none()
            if target is None:
                return []
            same = (
                Chunk.document_version_id == target.document_version_id,
                Chunk.index_generation_id == target.index_generation_id,
            )
            preceding = (
                await session.execute(
                    _scoped(scope, *_candidate_columns())
                    .where(*same, Chunk.ordinal < target.ordinal)
                    .order_by(Chunk.ordinal.desc())
                    .limit(before)
                )
            ).all()
            following = (
                await session.execute(
                    _scoped(scope, *_candidate_columns())
                    .where(*same, Chunk.ordinal > target.ordinal)
                    .order_by(Chunk.ordinal)
                    .limit(after)
                )
            ).all()
            return [
                RankedHit(candidate=_candidate(row)) for row in (*reversed(preceding), *following)
            ]

        if before < 0 or after < 0:
            raise ValueError("neighbor counts can't be negative")
        return await self._in_tenant(scope, load)
