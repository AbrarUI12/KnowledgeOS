"""Grounded question answering (S28-S29, T5.3 + T5.4): `/query` and its SSE stream.

Two phases, so no database transaction is open while a model generates (plan §8.2, S29):

1. `prepare` runs in the request's transaction: normalize → KB access (404/403 like search) →
   profile + model policy → permission-aware hybrid search → RRF → rerank → token-budgeted
   packing with `[S#]` aliases → a `running` query run with its retrieval hits. The route commits
   before returning.
2. `events` runs without a transaction: grounded generation (T5.2: untrusted-evidence prompt,
   abstention, one bounded citation correction, fail-safe), then the server-side sanitizer, then
   a short tenant transaction that persists the answer, its citations and the run's outcome.

The validated answer is sent as `answer_delta` blocks after validation: an answer whose citations
fail is never shown, even partially (DV-009). Conflict detection is cut for M1 (DV-008), so
`conflicts` is always empty and `evidence_status` never `conflicting`.
"""

import asyncio
import re
import time
import uuid
from collections.abc import AsyncGenerator, Callable, Coroutine
from dataclasses import dataclass, field, replace
from typing import Any

import structlog
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import AppError, RateLimited, ServiceUnavailable, ValidationFailed
from app.auth.authorization import RequestContext
from app.db.base import new_uuid
from app.db.models import Answer, Citation, Document, QueryRun
from app.db.tenant import tenant_session
from app.domain.enums import Classification, EvidenceStatus
from app.domain.schemas.retrieval import (
    AnswerOut,
    QueryRequest,
    StreamAnswerDelta,
    StreamCitation,
    StreamDone,
    StreamError,
    StreamMeta,
    StreamSources,
    StreamStage,
    Timing,
)
from app.domain.schemas.retrieval import Citation as CitationOut
from app.providers.llm.base import LLMRateLimitedError, LLMUnavailableError
from app.providers.search.base import QueryFilters
from app.rag.citations.validator import validate_citations
from app.rag.generation.grounded import (
    ABSTENTION,
    GroundedAnswer,
    evidence_insufficient,
    generate_grounded,
)
from app.rag.generation.prompt import PromptBudgetError
from app.rag.orchestration.generation import Generator, PolicyView, model_policy, sanitize_answer
from app.rag.orchestration.profiles import ActiveProfile, active_profile
from app.rag.query import normalize_query
from app.rag.types import EvidenceItem, RankedHit, SourceAlias, Usage
from app.services.search import (
    ContextSelection,
    SearchDeps,
    _hit_rows,
    _principal_summary,
    _queryable_kbs,
    retrieve,
    select_context,
)

logger = structlog.get_logger(__name__)
KEEP_ALIVE_SECONDS = 15.0
_RETRIEVAL_DEGRADED = {"dense_unavailable", "lexical_unavailable", "dense_model_mismatch"}
_BLOCKS = re.compile(r"(?<=\n\n)")
_BACKGROUND: set[asyncio.Task[None]] = set()  # persistence that must outlive a cancelled stream


@dataclass(frozen=True, slots=True)
class QueryDeps:
    search: SearchDeps
    generator_for: Callable[[PolicyView], Generator]


@dataclass(slots=True)
class Prepared:
    """The retrieval phase's result: everything generation needs, nothing tied to a session."""

    run_id: uuid.UUID
    organization_id: uuid.UUID
    user_id: uuid.UUID
    question: str
    profile: ActiveProfile
    generator: Generator
    evidence: tuple[EvidenceItem, ...]
    candidates: int
    degraded: list[str]
    retrieval_ms: float
    rerank_ms: float | None
    started: float
    threshold: float | None = None
    usage: Usage = field(default_factory=Usage)


def _filters(body: QueryRequest) -> QueryFilters | None:
    """The request's filters narrowed to its document scope; None when the two can't overlap
    (never widen to 'no filter')."""
    scope = tuple(dict.fromkeys(body.scope.document_ids))
    if not scope:
        return body.filters
    if body.filters.document_ids:
        scope = tuple(d for d in scope if d in set(body.filters.document_ids))
        if not scope:
            return None
    return body.filters.model_copy(update={"document_ids": scope})


async def prepare(
    session: AsyncSession,
    ctx: RequestContext,
    deps: QueryDeps,
    kb_id: uuid.UUID,
    body: QueryRequest,
) -> Prepared:
    started = time.perf_counter()
    try:
        query = normalize_query(body.question)
    except ValueError:
        raise ValidationFailed("The question is empty.") from None
    (kb,) = await _queryable_kbs(session, ctx, [kb_id])
    profile = await active_profile(session, kb)
    policy = await model_policy(session, kb)
    generator = deps.generator_for(policy)  # 503 before any work

    filters = _filters(body)
    evidence: tuple[EvidenceItem, ...] = ()
    degraded: list[str] = []
    candidates, retrieval_ms, rerank_ms = 0, 0.0, None
    context = None
    generations: dict[uuid.UUID, uuid.UUID] = {}
    embedding_model = reranker_model = None
    fused: list[RankedHit] = []
    if filters is not None:
        retrieval = await retrieve(session, ctx, deps.search, [kb], query, filters, profile)
        fused, degraded = retrieval.fused, list(retrieval.degraded)
        candidates, retrieval_ms = len(fused), retrieval.retrieval_ms
        generations, embedding_model = retrieval.generations, retrieval.embedding_model
        if fused:
            context = await select_context(deps.search, retrieval.scope, query.text, fused, profile)
            context, withheld = await _external_limit(session, context, generator, policy)
            evidence, rerank_ms = context.evidence, context.rerank_ms
            degraded += context.degraded + withheld
            reranker_model = context.reranker_model

    run = QueryRun(
        id=new_uuid(),
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        knowledge_base_ids=[kb.id],
        query_type="ask",
        status="running",
        query_hash=query.hash,
        query_text=query.text if deps.search.settings.retain_query_text else None,
        query_language=query.language,
        filters_json=(filters or body.filters).model_dump(mode="json", exclude_defaults=True),
        principal_summary=_principal_summary(ctx),
        index_generations_json={str(k): str(g) for k, g in generations.items()},
        embedding_model=embedding_model,
        rag_profile_version=profile.label,
        reranker_model=reranker_model,
        generation_model=generator.provider.model_id,
        degraded=degraded,
        retrieval_latency_ms=retrieval_ms,
        rerank_latency_ms=rerank_ms,
    )
    session.add(run)
    await session.flush()
    session.add_all(_hit_rows(run, ctx, fused, context))
    await session.flush()
    return Prepared(
        run_id=run.id,
        organization_id=ctx.organization_id,
        user_id=ctx.user_id,
        question=query.text,
        profile=profile,
        generator=generator,
        evidence=evidence,
        candidates=candidates,
        degraded=degraded,
        retrieval_ms=retrieval_ms,
        rerank_ms=rerank_ms,
        started=started,
        # A bypassed reranker gives no scores to judge by; abstain only on missing evidence then.
        threshold=None
        if "rerank_bypassed" in degraded
        else profile.config.abstain_min_rerank_score,
    )


_CLASSIFICATION_RANK = {c.value: rank for rank, c in enumerate(Classification)}


async def _external_limit(
    session: AsyncSession, context: ContextSelection, generator: Generator, policy: PolicyView
) -> tuple[ContextSelection, list[str]]:
    """Evidence an external model may see: documents at or below the policy's
    `max_external_classification` (plan §25.2). Unknown classifications are withheld (fail
    closed). Applies whenever any permitted generation target is external."""
    if not generator.provider.is_external or not context.evidence:
        return context, []
    limit = _CLASSIFICATION_RANK.get(policy.max_external_classification, 1)
    documents = {item.source.document_id for item in context.evidence}
    rows = await session.execute(
        select(Document.id, Document.classification).where(Document.id.in_(documents))
    )
    allowed = {doc for doc, label in rows.all() if _CLASSIFICATION_RANK.get(label, 99) <= limit}
    kept = tuple(item for item in context.evidence if item.source.document_id in allowed)
    if len(kept) == len(context.evidence):
        return context, []
    chunks = {item.source.chunk_id for item in kept}
    narrowed = replace(
        context, evidence=kept, selected=[h for h in context.selected if h.chunk_id in chunks]
    )
    return narrowed, ["evidence_withheld_external"]


def evidence_status(answer: GroundedAnswer, degraded: list[str]) -> EvidenceStatus:
    """Explicit rules, never model confidence (plan §21.3); conflicts are cut for M1."""
    if answer.abstained:
        return EvidenceStatus.INSUFFICIENT
    if _RETRIEVAL_DEGRADED.intersection(degraded):
        return EvidenceStatus.RETRIEVAL_DEGRADED
    if "rerank_bypassed" in degraded or "evidence_withheld_external" in degraded:
        return EvidenceStatus.PARTIAL
    return EvidenceStatus.STRONG


class GenerationFailed(AppError):
    status_code, code, message = 503, "generation_failed", "The answer couldn't be generated."


async def _generate(p: Prepared) -> GroundedAnswer:
    answer = await generate_grounded(
        p.question,
        p.evidence,
        provider=p.generator.provider,
        count_tokens=p.generator.count_tokens,
        max_input_tokens=p.generator.max_input_tokens,
        minimum_rerank_score=p.threshold,
        params=p.generator.params,
    )
    if answer.abstained:
        return answer
    clean = sanitize_answer(answer.text)
    if clean != answer.text:  # never trust the cleanup blindly: the citations must still hold
        checked = validate_citations(clean, p.evidence)
        if not checked.valid:
            return GroundedAnswer(
                text=ABSTENTION,
                abstained=True,
                abstain_reason="invalid_citations",
                closest_sources=tuple(item.source for item in p.evidence),
                usage=answer.usage,
                model=answer.model,
                provider=answer.provider,
                correction_attempted=answer.correction_attempted,
            )
        logger.info("answer_sanitized", query_run_id=str(p.run_id))
        answer = GroundedAnswer(
            text=clean,
            citations=checked.citations,
            usage=answer.usage,
            model=answer.model,
            provider=answer.provider,
            correction_attempted=answer.correction_attempted,
        )
    return answer


def _error(exc: Exception) -> AppError:
    """A safe client error: provider, budget and policy failures never leak details."""
    if isinstance(exc, AppError):
        return exc
    if isinstance(exc, LLMRateLimitedError):
        return RateLimited("The answer model is busy. Try again shortly.")
    if not isinstance(exc, (LLMUnavailableError, PromptBudgetError, PermissionError)):
        logger.error("query_generation_error", error_type=type(exc).__name__)
    return GenerationFailed()


def _timing(p: Prepared, generation_ms: float | None) -> Timing:
    return Timing(
        retrieval_ms=p.retrieval_ms,
        rerank_ms=p.rerank_ms,
        generation_ms=generation_ms,
        total_ms=(time.perf_counter() - p.started) * 1000,
    )


async def _persist(
    sessionmaker: async_sessionmaker[AsyncSession],
    p: Prepared,
    *,
    status: str,
    answer: GroundedAnswer | None = None,
    evidence: EvidenceStatus | None = None,
    timing: Timing | None = None,
) -> None:
    """The run's outcome in its own short tenant transaction (the retrieval one is closed)."""
    async with tenant_session(sessionmaker, p.organization_id, p.user_id) as session:
        values: dict[str, object] = {"status": status, "degraded": p.degraded}
        if timing is not None:
            values |= {
                "generation_latency_ms": timing.generation_ms,
                "total_latency_ms": timing.total_ms,
            }
        if answer is not None and answer.model:
            values["generation_model"] = answer.model
        await session.execute(update(QueryRun).where(QueryRun.id == p.run_id).values(**values))
        if answer is None:
            return
        row = Answer(
            id=new_uuid(),
            organization_id=p.organization_id,
            query_run_id=p.run_id,
            answer_markdown=answer.text,
            abstained=answer.abstained,
            abstain_reason=answer.abstain_reason,
            evidence_status=evidence.value if evidence else None,
            model=answer.model,
            input_tokens=answer.usage.input_tokens,
            output_tokens=answer.usage.output_tokens,
            usage_estimated=answer.usage.estimated,
        )
        session.add(row)
        await session.flush()
        session.add_all(
            Citation(
                answer_id=row.id,
                source_alias=source.alias,
                organization_id=p.organization_id,
                chunk_id=source.chunk_id,
                document_version_id=source.document_version_id,
                page_start=source.location.page_start,
                page_end=source.location.page_end,
                valid=True,
            )
            for source in answer.citations
        )


async def _safely(coro: Coroutine[Any, Any, None]) -> None:
    """Persist even while the stream is being cancelled: the write runs as its own task."""
    task = asyncio.create_task(coro)
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    try:
        await asyncio.shield(task)
    except Exception as exc:  # the run stays 'running'; log it, never break the response
        logger.warning("query_run_persist_failed", error_type=type(exc).__name__)


async def events(
    p: Prepared, sessionmaker: async_sessionmaker[AsyncSession]
) -> AsyncGenerator[tuple[str, BaseModel | None], None]:
    """The SSE event sequence of `docs/api/sse-events.md`. `("comment", None)` is a keep-alive."""
    finished = False
    task: asyncio.Task[GroundedAnswer] | None = None
    try:
        yield (
            "meta",
            StreamMeta(
                query_run_id=p.run_id, profile=p.profile.label, model=p.generator.provider.model_id
            ),
        )
        yield "stage", StreamStage(stage="retrieval.started")
        yield (
            "stage",
            StreamStage(
                stage="retrieval.completed", candidates=p.candidates, elapsed_ms=p.retrieval_ms
            ),
        )
        if p.rerank_ms is not None and "rerank_bypassed" not in p.degraded:
            yield "stage", StreamStage(stage="rerank.started")
            yield (
                "stage",
                StreamStage(
                    stage="rerank.completed", candidates=len(p.evidence), elapsed_ms=p.rerank_ms
                ),
            )
        early = evidence_insufficient(p.evidence, minimum_rerank_score=p.threshold)
        if early is None:
            yield "sources", StreamSources(sources=[item.source for item in p.evidence])
            yield "stage", StreamStage(stage="generation.started")
        generation_started = time.perf_counter()
        task = asyncio.create_task(_generate(p))
        while True:
            done, _ = await asyncio.wait({task}, timeout=KEEP_ALIVE_SECONDS)
            if done:
                break
            yield "comment", None
        try:
            answer = task.result()
        except Exception as exc:
            error = _error(exc)
            logger.warning("query_generation_failed", error_type=type(exc).__name__)
            finished = True
            await _safely(_persist(sessionmaker, p, status="failed", timing=_timing(p, None)))
            yield "error", StreamError(code=error.code, message=error.message)
            return
        generation_ms = (time.perf_counter() - generation_started) * 1000 if early is None else None
        status = evidence_status(answer, p.degraded)
        timing = _timing(p, generation_ms)
        finished = True
        await _safely(
            _persist(
                sessionmaker,
                p,
                status="abstained" if answer.abstained else "completed",
                answer=answer,
                evidence=status,
                timing=timing,
            )
        )
        for block in _BLOCKS.split(answer.text):
            if block:
                yield "answer_delta", StreamAnswerDelta(text=block)
        for source in answer.citations:
            yield (
                "citation",
                StreamCitation(alias=source.alias, chunk_id=source.chunk_id, valid=True),
            )
        yield (
            "done",
            StreamDone(
                abstained=answer.abstained,
                abstain_reason=answer.abstain_reason,
                evidence_status=status,
                usage=answer.usage,
                timing=timing,
                degraded=bool(p.degraded),
            ),
        )
    finally:
        if task is not None and not task.done():
            task.cancel()
        if not finished:  # the client went away: generation is cancelled with the stream
            await _safely(_persist(sessionmaker, p, status="cancelled", timing=_timing(p, None)))


async def answer(p: Prepared, sessionmaker: async_sessionmaker[AsyncSession]) -> AnswerOut:
    """The non-streaming `/query`: the same sequence, collected into one response."""
    sources: list[SourceAlias] = []
    citations: list[CitationOut] = []
    text: list[str] = []
    async for _name, payload in events(p, sessionmaker):
        if isinstance(payload, StreamSources):
            sources = payload.sources
        elif isinstance(payload, StreamAnswerDelta):
            text.append(payload.text)
        elif isinstance(payload, StreamCitation) and payload.chunk_id is not None:
            citations.append(CitationOut(alias=payload.alias, chunk_id=payload.chunk_id))
        elif isinstance(payload, StreamError):
            if payload.code == RateLimited.code:
                raise RateLimited(payload.message)
            if payload.code == GenerationFailed.code:
                raise GenerationFailed(payload.message)
            raise ServiceUnavailable(payload.message)
        elif isinstance(payload, StreamDone):
            return AnswerOut(
                query_run_id=p.run_id,
                answer_markdown="".join(text),
                abstained=payload.abstained,
                abstain_reason=payload.abstain_reason,
                evidence_status=payload.evidence_status,
                # On abstention: the closest authorized sources (S28), never more than retrieved.
                sources=sources or [item.source for item in p.evidence],
                citations=citations,
                usage=payload.usage,
                timing=payload.timing,
                degraded=payload.degraded,
            )
    raise GenerationFailed()
