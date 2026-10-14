"""Ingestion job operations (S20, T3.6): list, timeline, retry, cancel, reindex.

Visibility follows the document (KB visibility + document ACL), exactly like the read APIs in
`app.services.documents`. Mutations are audited and re-queue work through the outbox, so the
worker picks them up the same way as a fresh upload.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import Conflict, Forbidden, NotFound
from app.auth.authorization import RequestContext
from app.auth.kb_access import can_manage
from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import Chunk, Document, DocumentVersion, IngestionJob, JobEvent, KnowledgeBase
from app.domain.enums import ApprovalStatus, IngestionState
from app.domain.schemas.common import Page
from app.domain.schemas.knowledge import (
    ChunkSummary,
    DocumentInspection,
    IngestionJobEvent,
    IngestionJobOut,
)
from app.ingestion.canonical import CanonicalDocument, SourceLocation
from app.ingestion.stages.pipeline import MAX_CANONICAL_BYTES
from app.ingestion.state_machine import STAGES, ensure_transition, is_terminal
from app.providers.storage import ObjectStore, ObjectStoreError
from app.security.content_types import ContentFinding
from app.services import audit, outbox
from app.services.documents import (
    _visible_document,
    document_readable,
    get_ingestion_job,
    list_versions,
)
from app.services.knowledge_bases import load_kb
from app.services.pagination import after_cursor, encode_cursor, page_limit

S = IngestionState
_NOT_FOUND = "The ingestion job was not found."
# Stages whose checkpoints a reindex keeps: everything before CHUNKING (the canonical artifact,
# its normalization and its content-scan outcome stay valid; chunking onward runs again).
_REINDEX_KEEPS = STAGES[: STAGES.index(S.CHUNKING)]


async def _job_and_document(
    session: AsyncSession, ctx: RequestContext, job_id: uuid.UUID, *, lock: bool = False
) -> tuple[IngestionJob, uuid.UUID]:
    query = (
        select(IngestionJob, DocumentVersion.document_id)
        .join(DocumentVersion, DocumentVersion.id == IngestionJob.document_version_id)
        .where(IngestionJob.id == job_id, IngestionJob.organization_id == ctx.organization_id)
    )
    if lock:
        query = query.with_for_update(of=IngestionJob)
    row = (await session.execute(query)).one_or_none()
    if row is None:
        raise NotFound(_NOT_FOUND)
    job, document_id = row
    try:
        await _visible_document(session, ctx, document_id)
    except NotFound:
        raise NotFound(_NOT_FOUND) from None
    return job, document_id


async def list_jobs(
    session: AsyncSession,
    ctx: RequestContext,
    kb_id: uuid.UUID,
    *,
    states: list[IngestionState] | None,
    cursor: str | None,
    limit: int,
) -> Page[IngestionJobOut]:
    kb, kb_acl = await load_kb(session, ctx, kb_id)
    limit = page_limit(limit)
    query = (
        select(IngestionJob.id, IngestionJob.created_at)
        .join(DocumentVersion, DocumentVersion.id == IngestionJob.document_version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(
            IngestionJob.organization_id == ctx.organization_id, Document.knowledge_base_id == kb.id
        )
        .order_by(IngestionJob.created_at, IngestionJob.id)
    )
    if not can_manage(ctx, kb_acl):
        query = query.where(document_readable(ctx))
    if states:
        query = query.where(IngestionJob.state.in_([s.value for s in states]))
    if (clause := after_cursor(IngestionJob.created_at, IngestionJob.id, cursor)) is not None:
        query = query.where(clause)
    rows = list((await session.execute(query.limit(limit + 1))).all())
    items = [await get_ingestion_job(session, ctx, row.id) for row in rows[:limit]]
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = encode_cursor(last.created_at, last.id)
    return Page[IngestionJobOut](items=items, next_cursor=next_cursor)


async def list_events(
    session: AsyncSession, ctx: RequestContext, job_id: uuid.UUID
) -> list[IngestionJobEvent]:
    job, _ = await _job_and_document(session, ctx, job_id)
    events = await session.scalars(
        select(JobEvent)
        .where(JobEvent.job_id == job.id, JobEvent.organization_id == ctx.organization_id)
        .order_by(JobEvent.created_at, JobEvent.id)
    )
    return [
        IngestionJobEvent(
            at=event.created_at,
            state=IngestionState(event.state),
            stage=event.stage,
            message=event.message_safe,
        )
        for event in events
    ]


async def _active_job_exists(session: AsyncSession, version_id: uuid.UUID) -> bool:
    states = [state.value for state in IngestionState if not is_terminal(state)]
    found = await session.scalar(
        select(IngestionJob.id).where(
            IngestionJob.document_version_id == version_id, IngestionJob.state.in_(states)
        )
    )
    return found is not None


async def _new_job(
    session: AsyncSession,
    ctx: RequestContext,
    version: DocumentVersion,
    checkpoints: dict[str, object],
    reason: str,
) -> IngestionJob:
    # A job that inherits checkpoints starts *at* the last stage they cover: those stages really
    # completed (in the earlier job), so the next transition is a normal, table-checked one and
    # no scan can be skipped. Without checkpoints it starts from RECEIVED.
    done = [stage for stage in STAGES if stage.value in checkpoints]
    start = done[-1] if done else S.RECEIVED
    job = IngestionJob(
        id=new_uuid(),
        organization_id=ctx.organization_id,
        document_version_id=version.id,
        state=start.value,
        stage=start.value if done else None,
        stage_checkpoints=checkpoints,
    )
    session.add(job)
    version.ingestion_status = start.value
    await session.flush()
    session.add(
        JobEvent(
            id=new_uuid(),
            organization_id=ctx.organization_id,
            job_id=job.id,
            state=start.value,
            stage=job.stage,
            message_safe=reason,
        )
    )
    await outbox.emit(
        session,
        ctx,
        "ingestion.requested",
        "ingestion_job",
        job.id,
        {"document_version_id": str(version.id), "reason": reason},
    )
    return job


async def retry_job(
    session: AsyncSession, ctx: RequestContext, job_id: uuid.UUID
) -> IngestionJobOut:
    """Resume a failed job from its checkpoints.

    FAILED_RETRYABLE → re-queued now (same job, backoff skipped). FAILED_PERMANENT or a user
    cancellation → a new job for the same version that keeps the old job's checkpoints, so it
    resumes at the stage that failed. Quarantined or reviewer-rejected versions can't be retried.
    """
    job, _ = await _job_and_document(session, ctx, job_id, lock=True)
    state = IngestionState(job.state)
    version = await session.get(DocumentVersion, job.document_version_id)
    assert version is not None  # noqa: S101 (FK)
    if state is S.FAILED_RETRYABLE:
        await outbox.emit(
            session, ctx, "ingestion.requested", "ingestion_job", job.id, {"reason": "manual_retry"}
        )
        target = job
    elif state in {S.FAILED_PERMANENT, S.CANCELLED}:
        if version.approval_status == ApprovalStatus.REJECTED.value:
            raise Conflict("A reviewer rejected this version; upload a new one instead.")
        if await _active_job_exists(session, version.id):
            raise Conflict("This version already has an ingestion job in progress.")
        target = await _new_job(
            session, ctx, version, dict(job.stage_checkpoints or {}), "manual_retry"
        )
    else:
        raise Conflict("Only failed or cancelled jobs can be retried.")
    await audit.record(
        session,
        ctx,
        "ingestion.retried",
        "ingestion_job",
        target.id,
        {"previous_job_id": str(job.id)},
    )
    await session.flush()
    return await get_ingestion_job(session, ctx, target.id)


async def cancel_job(
    session: AsyncSession, ctx: RequestContext, job_id: uuid.UUID
) -> IngestionJobOut:
    """Cancel a job that hasn't finished. A worker mid-stage loses its lease: its in-flight stage
    rolls back at the checkpoint write and nothing further runs."""
    job, _ = await _job_and_document(session, ctx, job_id, lock=True)
    state = IngestionState(job.state)
    if is_terminal(state):
        raise Conflict("This job has already finished.")
    ensure_transition(state, S.CANCELLED)
    now = datetime.now(UTC)
    job.state = S.CANCELLED.value
    job.lease_owner = None
    job.lease_expires_at = None
    job.completed_at = now
    job.updated_at = now
    job.error_code = "cancelled_by_user"
    job.error_detail_safe = "Processing was cancelled."
    await session.execute(
        update(DocumentVersion)
        .where(DocumentVersion.id == job.document_version_id)
        .values(ingestion_status=S.CANCELLED.value)
    )
    session.add(
        JobEvent(
            id=new_uuid(),
            organization_id=ctx.organization_id,
            job_id=job.id,
            state=S.CANCELLED.value,
            stage=job.stage,
            attempt=job.attempt_count,
            message_safe="Processing was cancelled.",
        )
    )
    await audit.record(session, ctx, "ingestion.cancelled", "ingestion_job", job.id)
    await session.flush()
    return await get_ingestion_job(session, ctx, job.id)


async def reindex_document(
    session: AsyncSession, ctx: RequestContext, document_id: uuid.UUID
) -> IngestionJobOut:
    """Re-run chunking onward for the document's active version from its stored canonical
    artifact (new chunker settings, a new index generation). Validation, scanning, parsing and
    the content scan are not repeated."""
    document = await _visible_document(session, ctx, document_id, lock=True)
    if document.active_version_id is None:
        raise Conflict("The document has no processed version to reindex yet.")
    version = await session.get(DocumentVersion, document.active_version_id)
    assert version is not None  # noqa: S101 (FK)
    if not version.canonical_artifact_key:
        raise Conflict("The document's parsed artifact is missing; retry ingestion instead.")
    if await _active_job_exists(session, version.id):
        raise Conflict("This version already has an ingestion job in progress.")
    finished = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.document_version_id == version.id, IngestionJob.state == S.READY.value)
        .order_by(IngestionJob.completed_at.desc())
        .limit(1)
    )
    if finished is None:
        raise Conflict("The document has no completed ingestion to reindex from.")
    kept = {
        k: v
        for k, v in (finished.stage_checkpoints or {}).items()
        if k in {s.value for s in _REINDEX_KEEPS}
    }
    job = await _new_job(session, ctx, version, kept, "reindex")
    await audit.record(
        session, ctx, "document.reindexed", "document", document.id, {"job_id": str(job.id)}
    )
    await session.flush()
    return await get_ingestion_job(session, ctx, job.id)


async def inspect_version(
    session: AsyncSession,
    ctx: RequestContext,
    store: ObjectStore,
    settings: Settings,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
) -> DocumentInspection:
    """Inspect mode (S21): the canonical artifact, chunk boundaries of the active generation and
    the content-scan findings, for KB managers only (it shows the full document content)."""
    document = await _visible_document(session, ctx, document_id)
    _, kb_acl = await load_kb(session, ctx, document.knowledge_base_id)
    if not can_manage(ctx, kb_acl):
        raise Forbidden("Inspect mode needs manage access to the knowledge base.")
    versions = await list_versions(session, ctx, document.id)
    version_out = next((v for v in versions if v.id == version_id), None)
    version = await session.get(DocumentVersion, version_id)
    if version_out is None or version is None:
        raise NotFound("The document version was not found.")

    canonical = None
    if version.canonical_artifact_key:
        try:
            data = await store.get_bytes(
                settings.s3_bucket_artifacts,
                version.canonical_artifact_key,
                max_bytes=MAX_CANONICAL_BYTES,
            )
            canonical = CanonicalDocument.model_validate_json(data)
        except ObjectStoreError:
            canonical = None  # artifact unavailable: the rest of the inspection still helps

    generation_id = await session.scalar(
        select(KnowledgeBase.active_index_generation_id).where(
            KnowledgeBase.id == document.knowledge_base_id
        )
    )
    chunks = await session.scalars(
        select(Chunk)
        .where(Chunk.document_version_id == version.id, Chunk.index_generation_id == generation_id)
        .order_by(Chunk.ordinal)
    )
    summaries = [
        ChunkSummary(
            id=chunk.id,
            ordinal=chunk.ordinal,
            token_count=chunk.token_count,
            section_path=list(chunk.section_path),
            location=SourceLocation.model_validate(chunk.location_json or {}),
            block_ids=list(chunk.block_ids),
        )
        for chunk in chunks
    ]

    latest = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.document_version_id == version.id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    scan = ((latest.stage_checkpoints or {}) if latest else {}).get(S.SECURITY_SCAN.value, {})
    findings = [ContentFinding.model_validate(f) for f in scan.get("findings", [])]
    return DocumentInspection(
        version=version_out, canonical=canonical, chunks=summaries, content_findings=findings
    )
