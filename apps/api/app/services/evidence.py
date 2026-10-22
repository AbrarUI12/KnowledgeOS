"""Evidence endpoints (S31 backend, T5.4): open a cited source, read a chunk's surroundings, and
leave feedback on a run.

Every read here is a *content* read, so it needs what search needs: KB query access and the
document's own ACL (`can_read_content`, or the search authorization predicate for chunks).
Managing a KB never opens content. Chunks are read through the same predicate as retrieval, so
an inactive generation, a superseded version or an archived document can't be opened by id.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import Conflict, Forbidden, Gone, NotFound
from app.auth.authorization import RequestContext, principal_tokens
from app.auth.kb_access import can_query
from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import Chunk, DocumentVersion, Feedback, KnowledgeBase, QueryRun, Upload
from app.domain.enums import DocumentStatus, Visibility
from app.domain.schemas.knowledge import ChunkContext, ChunkSummary, ContentUrl
from app.domain.schemas.retrieval import FeedbackCreate, FeedbackOut
from app.ingestion.canonical import SourceLocation
from app.providers.search.base import SearchBackend, SearchScope
from app.providers.search.postgres import authorization_predicate
from app.providers.storage import ObjectStore, trusted_original_key
from app.services.documents import _visible_document, can_read_content
from app.services.knowledge_bases import load_kb

CONTENT_URL_SECONDS = 300
_CHUNK_NOT_FOUND = "The passage was not found."


async def content_url(
    session: AsyncSession,
    ctx: RequestContext,
    store: ObjectStore,
    settings: Settings,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
) -> ContentUrl:
    """A five-minute link to the version's trusted original (never the quarantine copy), only
    while the document and its KB are active."""
    document = await _visible_document(session, ctx, document_id)  # 404 unless visible
    if not await can_read_content(session, ctx, document):
        raise Forbidden("You can't open this document's content.")
    # Archiving takes content out of retrieval; it must not stay downloadable either.
    kb_archived = await session.scalar(
        select(KnowledgeBase.archived_at).where(KnowledgeBase.id == document.knowledge_base_id)
    )
    if (
        document.status != DocumentStatus.ACTIVE.value
        or document.archived_at is not None
        or kb_archived is not None
    ):
        raise Gone("This document is archived; its content is no longer available.")
    version = await session.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id, DocumentVersion.document_id == document.id
        )
    )
    if version is None:
        raise NotFound("The document version was not found.")
    trusted = trusted_original_key(
        ctx.organization_id, document.knowledge_base_id, document.id, version.id
    )
    if version.object_key != trusted:  # not scanned and promoted (yet), or quarantined
        raise Conflict("This version's original isn't available.")
    filename = await session.scalar(
        select(Upload.filename).where(Upload.document_version_id == version.id)
    )
    link = await store.presign_get(
        settings.s3_bucket_trusted,
        trusted,
        expires_in_seconds=CONTENT_URL_SECONDS,
        filename=filename or document.title,
    )
    return ContentUrl(url=link.url, expires_at=link.expires_at)


def _summary(chunk: Chunk) -> ChunkSummary:
    return ChunkSummary(
        id=chunk.id,
        ordinal=chunk.ordinal,
        token_count=chunk.token_count,
        section_path=list(chunk.section_path),
        location=SourceLocation.model_validate(chunk.location_json or {}),
        block_ids=list(chunk.block_ids),
    )


async def chunk_context(
    session: AsyncSession,
    ctx: RequestContext,
    backend: SearchBackend,
    chunk_id: uuid.UUID,
    *,
    before: int,
    after: int,
) -> ChunkContext:
    """The passage and its neighbors (evidence rail 'surrounding context'), all authorized the
    way retrieval is. Anything the caller couldn't retrieve is 404, never 403."""
    kb_id = await session.scalar(select(Chunk.knowledge_base_id).where(Chunk.id == chunk_id))
    if kb_id is None:
        raise NotFound(_CHUNK_NOT_FOUND)
    try:
        kb, acl = await load_kb(session, ctx, kb_id)
    except NotFound:
        raise NotFound(_CHUNK_NOT_FOUND) from None
    if not can_query(ctx, Visibility(kb.visibility), acl):
        raise NotFound(_CHUNK_NOT_FOUND)
    scope = SearchScope(
        organization_id=ctx.organization_id,
        knowledge_base_ids=(kb.id,),
        principal_tokens=tuple(principal_tokens(ctx)),
    )
    chunk = await session.scalar(
        select(Chunk).where(Chunk.id == chunk_id, *authorization_predicate(scope))
    )
    if chunk is None:
        raise NotFound(_CHUNK_NOT_FOUND)
    neighbors = await backend.neighbors(scope, chunk.id, before=before, after=after)
    return ChunkContext(
        chunk=_summary(chunk),
        content=chunk.content,
        before=[h.candidate.content for h in neighbors if h.candidate.ordinal < chunk.ordinal],
        after=[h.candidate.content for h in neighbors if h.candidate.ordinal > chunk.ordinal],
    )


async def give_feedback(
    session: AsyncSession, ctx: RequestContext, run_id: uuid.UUID, body: FeedbackCreate
) -> FeedbackOut:
    """Rate a run you made; rating it again replaces your previous feedback."""
    owner = await session.scalar(
        select(QueryRun.user_id).where(
            QueryRun.id == run_id, QueryRun.organization_id == ctx.organization_id
        )
    )
    if owner is None or owner != ctx.user_id:
        raise NotFound("The query run was not found.")
    now = datetime.now(UTC)
    statement = (
        insert(Feedback)
        .values(
            id=new_uuid(),
            organization_id=ctx.organization_id,
            query_run_id=run_id,
            user_id=ctx.user_id,
            rating=body.rating.value,
            reason_code=body.reason_code,
            comment=body.comment,
        )
        .on_conflict_do_update(
            constraint="uq_feedback_run_user",
            set_={
                "rating": body.rating.value,
                "reason_code": body.reason_code,
                "comment": body.comment,
                "updated_at": now,
            },
        )
        .returning(Feedback.id, Feedback.created_at)
    )
    row = (await session.execute(statement)).one()
    return FeedbackOut(id=row.id, created_at=row.created_at)
