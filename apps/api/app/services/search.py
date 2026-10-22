"""Search API and query runs (S25-S26, T4.6).

Search = normalize → resolve the KBs the caller may query (404 if they can't see one, 403 if they
can see but not read it) → embed the query with the model the KBs' active generations recorded
→ permission-aware hybrid search (T4.4) → weighted RRF (T4.3) → snippets → a persisted query
run with its retrieval hits. The query's text is stored only when retention allows; its hash
always.

Query runs are visible to the person who ran them, and in full (debug) to holders of
`retrieval.debug`, who still never see documents they couldn't read themselves: debug hits are
filtered through the viewer's own access, and the principal summary names no documents.
"""

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import Forbidden, NotFound, UnsupportedSearchFilter, ValidationFailed
from app.auth.authorization import RequestContext, has_permission, principal_tokens
from app.auth.kb_access import can_query
from app.auth.permissions import Permission
from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import Document, IndexGeneration, KnowledgeBase, QueryRun, RetrievalHit
from app.domain.enums import MatchType, Visibility
from app.domain.schemas.retrieval import (
    DebugHit,
    QueryRunDebug,
    QueryRunOut,
    SearchHit,
    SearchRequest,
    SearchResponse,
    Timing,
)
from app.providers.embeddings.base import EmbeddingProvider, EmbeddingUnavailableError
from app.providers.search.base import (
    HybridSearchRequest,
    QueryFilters,
    SearchBackend,
    SearchScope,
)
from app.providers.search.postgres import UnsupportedFilter
from app.rag.fusion.rrf import reciprocal_rank_fusion
from app.rag.query import NormalizedQuery, normalize_query
from app.rag.types import RankedHit
from app.services.documents import document_readable
from app.services.knowledge_bases import load_kb

logger = structlog.get_logger(__name__)
_RUN_NOT_FOUND = "The query run was not found."
_SNIPPET_CHARACTERS = 240
# ts_headline options: plain-text snippets with «…» around matched terms (SearchHit.snippet).
_HEADLINE = "StartSel=«, StopSel=», MaxWords=35, MinWords=15, MaxFragments=2, FragmentDelimiter= … "


@dataclass(frozen=True, slots=True)
class SearchDeps:
    backend: SearchBackend
    embedder: EmbeddingProvider | None
    settings: Settings


def _principal_summary(ctx: RequestContext) -> str:
    groups = len(ctx.group_ids)
    return f"role {ctx.role}, {groups} group{'s' if groups != 1 else ''}"


async def _queryable_kbs(
    session: AsyncSession, ctx: RequestContext, kb_ids: Sequence[uuid.UUID]
) -> list[KnowledgeBase]:
    kbs = []
    for kb_id in dict.fromkeys(kb_ids):  # deduplicated, order kept
        kb, acl = await load_kb(session, ctx, kb_id)  # 404 unless visible
        if not can_query(ctx, Visibility(kb.visibility), acl):
            raise Forbidden(
                "You can't search this knowledge base's content.",
                details={"knowledge_base_id": str(kb.id)},
            )
        if kb.archived_at is not None:
            raise NotFound("The knowledge base was not found.")
        kbs.append(kb)
    return kbs


async def _query_vector(
    session: AsyncSession, deps: SearchDeps, kbs: Sequence[KnowledgeBase], query: NormalizedQuery
) -> tuple[tuple[float, ...] | None, str | None, dict[uuid.UUID, uuid.UUID], list[str]]:
    """The query embedding with the model the KBs' generations recorded, the generation per KB,
    and degradation notes. A KB on another model is searched lexically only, never with a vector
    from a different model (plan §25.2)."""
    generation_ids = [kb.active_index_generation_id for kb in kbs if kb.active_index_generation_id]
    generations = list(
        await session.scalars(select(IndexGeneration).where(IndexGeneration.id.in_(generation_ids)))
    )
    per_kb = {g.knowledge_base_id: g.id for g in generations}
    embedder = deps.embedder
    if embedder is None:
        return None, None, per_kb, ["dense_unavailable"]
    compatible = [
        (g.embedding_model, g.embedding_dimension) == (embedder.model_id, embedder.dimension)
        for g in generations
    ]
    if not any(compatible):
        return None, None, per_kb, ["dense_model_mismatch"]
    # Some KBs on another model: dense still covers the compatible ones, the rest is lexical only.
    degraded = [] if all(compatible) else ["dense_model_mismatch"]
    try:
        vector = await embedder.embed_query(query.text)
    except (EmbeddingUnavailableError, ValueError) as exc:
        logger.warning("search_query_embedding_failed", error_type=type(exc).__name__)
        return None, None, per_kb, ["dense_unavailable"]
    return tuple(vector), embedder.model_id, per_kb, degraded


async def _snippets(
    session: AsyncSession, hits: Sequence[RankedHit], query: str
) -> dict[uuid.UUID, str]:
    """ts_headline for lexical hits; semantic-only hits use their leading passage."""
    snippets = {}
    for hit in hits:
        content = " ".join(hit.candidate.content.split())
        if len(content) > _SNIPPET_CHARACTERS:
            content = content[:_SNIPPET_CHARACTERS].rsplit(" ", 1)[0] + " …"
        snippets[hit.chunk_id] = content
    lexical = [hit.chunk_id for hit in hits if hit.lexical_rank is not None]
    if lexical:
        rows = await session.execute(
            text(
                "SELECT id, ts_headline(fts_config, content, websearch_to_tsquery(fts_config, :q), "
                ":options) AS snippet FROM chunks WHERE id = ANY(:ids) AND fts_config IS NOT NULL"
            ),
            {"q": query, "options": _HEADLINE, "ids": lexical},
        )
        for chunk_id, snippet in rows.all():
            if "«" in snippet:  # a full-text match; title-trigram hits keep the leading passage
                snippets[chunk_id] = " ".join(snippet.split())
    return snippets


def _match_type(hit: RankedHit) -> MatchType:
    if hit.dense_rank is not None and hit.lexical_rank is not None:
        return MatchType.BOTH
    return MatchType.SEMANTIC if hit.dense_rank is not None else MatchType.EXACT


async def search(
    session: AsyncSession,
    ctx: RequestContext,
    deps: SearchDeps,
    kb_ids: Sequence[uuid.UUID],
    body: SearchRequest,
) -> SearchResponse:
    started = time.perf_counter()
    if body.debug and not has_permission(ctx, Permission.RETRIEVAL_DEBUG):
        raise Forbidden(details={"permission": Permission.RETRIEVAL_DEBUG.value})
    try:
        query = normalize_query(body.query)
    except ValueError:
        raise ValidationFailed("The query is empty.") from None
    kbs = await _queryable_kbs(session, ctx, kb_ids)
    vector, model, generations, degraded = await _query_vector(session, deps, kbs, query)
    request = HybridSearchRequest(
        scope=SearchScope(
            organization_id=ctx.organization_id,
            knowledge_base_ids=tuple(kb.id for kb in kbs),
            principal_tokens=tuple(principal_tokens(ctx)),
        ),
        query=query.text,
        filters=body.filters,
        query_embedding=vector,
        embedding_model=model,
        dense_k=deps.settings.search_max_candidates,
        lexical_k=deps.settings.search_max_candidates,
    )
    retrieval_started = time.perf_counter()
    try:
        result = await deps.backend.hybrid_search(request)
    except UnsupportedFilter as exc:
        raise UnsupportedSearchFilter(details={"reason": str(exc)}) from None
    retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
    if result.degraded.dense_unavailable and "dense_unavailable" not in degraded:
        degraded.append("dense_unavailable")
    if result.degraded.lexical_unavailable:
        degraded.append("lexical_unavailable")
    fused = reciprocal_rank_fusion(result.dense, result.lexical)
    shown = fused[: body.limit]
    snippets = await _snippets(session, shown, query.text)

    run = QueryRun(
        id=new_uuid(),
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        knowledge_base_ids=[kb.id for kb in kbs],
        query_type="search",
        status="completed",
        query_hash=query.hash,
        query_text=query.text if deps.settings.retain_query_text else None,
        query_language=query.language,
        filters_json=body.filters.model_dump(mode="json", exclude_defaults=True),
        principal_summary=_principal_summary(ctx),
        index_generations_json={str(kb): str(g) for kb, g in result.index_generation_ids.items()}
        or {str(kb): str(g) for kb, g in generations.items()},
        embedding_model=model,
        degraded=degraded,
        retrieval_latency_ms=retrieval_ms,
    )
    session.add(run)
    await session.flush()
    session.add_all(
        RetrievalHit(
            query_run_id=run.id,
            chunk_id=hit.chunk_id,
            organization_id=ctx.organization_id,
            document_id=hit.candidate.document_id,
            knowledge_base_id=hit.candidate.knowledge_base_id,
            rank=rank,
            dense_rank=hit.dense_rank,
            dense_score=hit.dense_score,
            lexical_rank=hit.lexical_rank,
            lexical_score=hit.lexical_score,
            fusion_score=hit.fused_score,
        )
        for rank, hit in enumerate(fused, 1)
    )
    run.total_latency_ms = (time.perf_counter() - started) * 1000
    await session.flush()

    hits = [
        SearchHit(
            chunk_id=hit.chunk_id,
            document_id=hit.candidate.document_id,
            document_version_id=hit.candidate.document_version_id,
            knowledge_base_id=hit.candidate.knowledge_base_id,
            title=hit.candidate.title,
            section_path=list(hit.candidate.section_path),
            snippet=snippets[hit.chunk_id],
            match_type=_match_type(hit),
            location=hit.candidate.location,
            score=hit.fused_score or 0.0,
        )
        for hit in shown
    ]
    debug = await _debug(session, ctx, run) if body.debug else None
    return SearchResponse(query_run_id=run.id, hits=hits, degraded=bool(degraded), debug=debug)


# --------------------------------------------------------------------------- query runs


async def _readable_document_ids(
    session: AsyncSession, ctx: RequestContext, kb_ids: set[uuid.UUID], document_ids: set[uuid.UUID]
) -> set[uuid.UUID]:
    """The documents among `document_ids` whose content the viewer may read now."""
    queryable = set()
    for kb_id in kb_ids:
        try:
            kb, acl = await load_kb(session, ctx, kb_id)
        except NotFound:
            continue
        if can_query(ctx, Visibility(kb.visibility), acl):
            queryable.add(kb_id)
    if not queryable or not document_ids:
        return set()
    return set(
        await session.scalars(
            select(Document.id).where(
                Document.id.in_(document_ids),
                Document.knowledge_base_id.in_(queryable),
                document_readable(ctx),
            )
        )
    )


async def _debug(session: AsyncSession, ctx: RequestContext, run: QueryRun) -> QueryRunDebug:
    hits = list(
        await session.scalars(
            select(RetrievalHit)
            .where(RetrievalHit.query_run_id == run.id)
            .order_by(RetrievalHit.rank, RetrievalHit.chunk_id)
        )
    )
    readable = await _readable_document_ids(
        session, ctx, {h.knowledge_base_id for h in hits}, {h.document_id for h in hits}
    )
    titles = dict(
        (
            await session.execute(
                select(Document.id, Document.title).where(Document.id.in_(readable))
            )
        )
        .tuples()
        .all()
    )
    visible = [h for h in hits if h.document_id in readable]
    hidden = len(hits) - len(visible)
    generations = {uuid.UUID(k): uuid.UUID(v) for k, v in run.index_generations_json.items()}
    return QueryRunDebug(
        rag_profile_version=run.rag_profile_version,
        index_generation_id=next(iter(generations.values())) if len(generations) == 1 else None,
        index_generation_ids=generations,
        embedding_model=run.embedding_model,
        reranker_model=run.reranker_model,
        generation_model=run.generation_model,
        filters=QueryFilters.model_validate(run.filters_json),
        principal_summary=run.principal_summary
        + (f"; {hidden} hit{'s' if hidden != 1 else ''} hidden from you" if hidden else ""),
        hits=[
            DebugHit(
                chunk_id=h.chunk_id,
                document_id=h.document_id,
                title=titles.get(h.document_id, ""),
                dense_rank=h.dense_rank,
                dense_score=h.dense_score,
                lexical_rank=h.lexical_rank,
                lexical_score=h.lexical_score,
                fused_score=h.fusion_score,
                rerank_score=h.rerank_score,
                selected_for_context=h.selected_for_context,
            )
            for h in visible
        ],
        degraded=list(run.degraded),
    )


async def get_query_run(
    session: AsyncSession, ctx: RequestContext, run_id: uuid.UUID
) -> QueryRunOut:
    run = await session.scalar(
        select(QueryRun).where(
            QueryRun.id == run_id, QueryRun.organization_id == ctx.organization_id
        )
    )
    debugger = has_permission(ctx, Permission.RETRIEVAL_DEBUG)
    if run is None or (run.user_id != ctx.user_id and not debugger):
        raise NotFound(_RUN_NOT_FOUND)
    kb_ids = list(run.knowledge_base_ids)
    return QueryRunOut(
        id=run.id,
        knowledge_base_id=kb_ids[0] if len(kb_ids) == 1 else None,
        knowledge_base_ids=kb_ids,
        query_type=run.query_type,
        status=run.status,
        created_at=run.created_at,
        timing=Timing(
            retrieval_ms=run.retrieval_latency_ms,
            rerank_ms=run.rerank_latency_ms,
            generation_ms=run.generation_latency_ms,
            total_ms=run.total_latency_ms,
        ),
        trace_id=run.trace_id,
        debug=await _debug(session, ctx, run) if debugger else None,
    )


async def run_count(session: AsyncSession) -> int:
    """Query runs visible in this tenant transaction (tests and metrics)."""
    return int(await session.scalar(select(func.count()).select_from(QueryRun)) or 0)
