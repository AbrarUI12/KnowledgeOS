"""Secure upload flow and document reads (S13, T2.4).

Browsers PUT files straight to the quarantine bucket through a presigned URL. `complete` then
HEAD-verifies the object (presigned PUTs can't enforce size) and, in **one transaction**, creates
the document (or a new version), the version row, the ingestion job, the `ingestion.requested`
outbox event and the audit row. Either all of it commits or none of it does.

Documents inherit visibility from their knowledge base: anything in a KB the caller can't see
is 404.
"""

import base64
import binascii
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import PurePath
from typing import Any

from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import (
    FileTooLarge,
    KnowledgeBaseArchived,
    NotFound,
    SizeMismatch,
    UnsupportedFileType,
    UploadExpired,
    UploadNotReceived,
    ValidationFailed,
)
from app.auth.authorization import RequestContext
from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import DataSource, Document, DocumentVersion, IngestionJob, Upload
from app.domain.enums import ApprovalStatus, Classification, DocumentStatus, IngestionState
from app.domain.schemas.common import Page
from app.domain.schemas.knowledge import (
    DocumentOut,
    DocumentVersionOut,
    IngestionJobOut,
    UploadComplete,
    UploadCompleted,
    UploadCreate,
    UploadOut,
)
from app.providers.storage import ObjectStore, quarantine_original_key
from app.security.file_validation import SUPPORTED_EXTENSIONS
from app.services import audit, outbox
from app.services.knowledge_bases import load_kb
from app.services.pagination import page_limit

_DOC_NOT_FOUND = "The document was not found."
_UPLOAD_NOT_FOUND = "The upload was not found."


# --------------------------------------------------------------------------- uploads


def _check_file(body: UploadCreate, settings: Settings) -> None:
    extension = PurePath(body.filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise UnsupportedFileType(details={"extension": extension or None})
    if body.size_bytes > settings.upload_max_bytes:
        raise FileTooLarge(details={"max_bytes": settings.upload_max_bytes})


async def _visible_document(
    session: AsyncSession, ctx: RequestContext, document_id: uuid.UUID, *, lock: bool = False
) -> Document:
    query = select(Document).where(
        Document.id == document_id,
        Document.organization_id == ctx.organization_id,
        Document.status != DocumentStatus.DELETED.value,
    )
    if lock:
        query = query.with_for_update()
    document = await session.scalar(query)
    if document is None:
        raise NotFound(_DOC_NOT_FOUND)
    try:
        await load_kb(session, ctx, document.knowledge_base_id)
    except NotFound:
        raise NotFound(_DOC_NOT_FOUND) from None
    return document


async def create_upload(
    session: AsyncSession,
    ctx: RequestContext,
    store: ObjectStore,
    settings: Settings,
    kb_id: uuid.UUID,
    body: UploadCreate,
) -> UploadOut:
    """Validate the declared file, record the upload and presign a PUT to quarantine."""
    kb, _ = await load_kb(session, ctx, kb_id)
    if kb.archived_at is not None:
        raise KnowledgeBaseArchived
    _check_file(body, settings)
    if body.document_id is not None:
        document = await _visible_document(session, ctx, body.document_id)
        if document.knowledge_base_id != kb.id:
            raise NotFound(_DOC_NOT_FOUND)

    upload_id = new_uuid()
    key = quarantine_original_key(ctx.organization_id, kb.id, upload_id)
    ttl = settings.upload_url_ttl_seconds
    session.add(
        Upload(
            id=upload_id,
            organization_id=ctx.organization_id,
            knowledge_base_id=kb.id,
            document_id=body.document_id,
            created_by=ctx.user_id,
            filename=body.filename,
            declared_mime=body.content_type,
            declared_size=body.size_bytes,
            object_key=key,
            expires_at=datetime.now(UTC) + timedelta(seconds=ttl),
        )
    )
    await session.flush()
    presigned = await store.presign_put(
        settings.s3_bucket_quarantine, key, content_type=body.content_type, expires_in_seconds=ttl
    )
    return UploadOut(
        upload_id=upload_id,
        url=presigned.url,
        method=presigned.method,
        headers=presigned.headers,
        expires_at=presigned.expires_at,
    )


async def start_replacement(
    session: AsyncSession,
    ctx: RequestContext,
    store: ObjectStore,
    settings: Settings,
    document_id: uuid.UUID,
    body: UploadCreate,
) -> UploadOut:
    document = await _visible_document(session, ctx, document_id)
    replacement = body.model_copy(update={"document_id": document.id})
    return await create_upload(
        session, ctx, store, settings, document.knowledge_base_id, replacement
    )


async def _completed_result(session: AsyncSession, upload: Upload) -> UploadCompleted:
    row = (
        await session.execute(
            select(DocumentVersion, IngestionJob.id)
            .join(IngestionJob, IngestionJob.document_version_id == DocumentVersion.id)
            .where(DocumentVersion.id == upload.document_version_id)
            .order_by(IngestionJob.created_at)
            .limit(1)
        )
    ).one()
    version, job_id = row
    return UploadCompleted(
        document_id=version.document_id,
        document_version_id=version.id,
        ingestion_job_id=job_id,
        version_number=version.version_number,
    )


async def complete_upload(
    session: AsyncSession,
    ctx: RequestContext,
    store: ObjectStore,
    settings: Settings,
    upload_id: uuid.UUID,
    body: UploadComplete,
) -> UploadCompleted:
    upload = await session.scalar(
        select(Upload)
        .where(
            Upload.id == upload_id,
            Upload.organization_id == ctx.organization_id,
            Upload.created_by == ctx.user_id,  # only the uploader completes their upload
        )
        .with_for_update()  # concurrent completes serialize; the loser sees "completed"
    )
    if upload is None:
        raise NotFound(_UPLOAD_NOT_FOUND)
    kb, _ = await load_kb(session, ctx, upload.knowledge_base_id)
    if upload.status == "completed":
        return await _completed_result(session, upload)  # double complete is idempotent
    if upload.status != "pending":
        raise UploadExpired
    if upload.expires_at <= datetime.now(UTC):
        upload.status = "expired"
        raise UploadExpired
    if kb.archived_at is not None:
        raise KnowledgeBaseArchived

    info = await store.head(settings.s3_bucket_quarantine, upload.object_key)
    if info is None:
        raise UploadNotReceived
    if info.size_bytes != upload.declared_size or info.size_bytes > settings.upload_max_bytes:
        # Reject the bytes we can't trust; the client starts a new upload.
        await store.delete(settings.s3_bucket_quarantine, upload.object_key)
        raise SizeMismatch(
            details={"declared_bytes": upload.declared_size, "received_bytes": info.size_bytes}
        )

    replacing = upload.document_id is not None
    if upload.document_id is not None:
        document = await _visible_document(session, ctx, upload.document_id, lock=True)
    else:
        source_id = await session.scalar(
            select(DataSource.id).where(
                DataSource.organization_id == ctx.organization_id,
                DataSource.knowledge_base_id == kb.id,
                DataSource.type == "upload",
            )
        )
        document = Document(
            id=new_uuid(),
            organization_id=ctx.organization_id,
            knowledge_base_id=kb.id,
            source_id=source_id,
            title=body.title or PurePath(upload.filename).stem or upload.filename,
            classification=body.classification.value,
            created_by=ctx.user_id,
        )
        session.add(document)
        await session.flush()

    # The document row is locked (or brand new), so max + 1 can't race another version.
    next_version = (
        await session.scalar(
            select(func.coalesce(func.max(DocumentVersion.version_number), 0)).where(
                DocumentVersion.document_id == document.id
            )
        )
        or 0
    ) + 1
    version = DocumentVersion(
        id=new_uuid(),
        organization_id=ctx.organization_id,
        document_id=document.id,
        version_number=next_version,
        object_key=upload.object_key,
        mime_type=upload.declared_mime,
        size_bytes=info.size_bytes,
        integrity_status="pending",
        ingestion_status=IngestionState.RECEIVED.value,
        created_by=ctx.user_id,
    )
    session.add(version)
    await session.flush()
    job = IngestionJob(
        id=new_uuid(),
        organization_id=ctx.organization_id,
        document_version_id=version.id,
        state=IngestionState.RECEIVED.value,
    )
    session.add(job)
    document.updated_at = datetime.now(UTC)
    upload.status = "completed"
    upload.completed_at = datetime.now(UTC)
    upload.document_version_id = version.id
    upload.document_id = document.id
    await session.flush()

    await outbox.emit(
        session,
        ctx,
        "ingestion.requested",
        "ingestion_job",
        job.id,
        {"document_id": str(document.id), "document_version_id": str(version.id)},
    )
    await audit.record(
        session,
        ctx,
        "document.version_created" if replacing else "document.uploaded",
        "document",
        document.id,
        {"version_number": next_version, "size_bytes": info.size_bytes},
    )
    return UploadCompleted(
        document_id=document.id,
        document_version_id=version.id,
        ingestion_job_id=job.id,
        version_number=next_version,
    )


# --------------------------------------------------------------------------- reads


async def _latest_states(
    session: AsyncSession, document_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, str | None]]:
    """(latest version number, its ingestion state) per document."""
    latest = (
        select(
            DocumentVersion.document_id,
            DocumentVersion.version_number,
            DocumentVersion.ingestion_status,
            func.row_number()
            .over(
                partition_by=DocumentVersion.document_id,
                order_by=DocumentVersion.version_number.desc(),
            )
            .label("rn"),
        )
        .where(DocumentVersion.document_id.in_(document_ids))
        .subquery()
    )
    rows = await session.execute(
        select(latest.c.document_id, latest.c.version_number, latest.c.ingestion_status).where(
            latest.c.rn == 1
        )
    )
    return {doc_id: (number, state) for doc_id, number, state in rows}


def _document_out(document: Document, latest: tuple[int, str | None] | None) -> DocumentOut:
    number, state = latest or (0, None)
    return DocumentOut(
        id=document.id,
        knowledge_base_id=document.knowledge_base_id,
        title=document.title,
        document_type=document.document_type,
        classification=Classification(document.classification),
        status=DocumentStatus(document.status),
        active_version_id=document.active_version_id,
        latest_version_number=number,
        ingestion_state=IngestionState(state) if state else None,
        created_by=document.created_by,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _sort_column(field: str) -> Any:
    return {
        "title": Document.title,
        "created_at": Document.created_at,
        "updated_at": func.coalesce(Document.updated_at, Document.created_at),
    }[field]


def _sort_value(document: Document, field: str) -> str | datetime:
    if field == "title":
        return document.title
    if field == "updated_at":
        return document.updated_at or document.created_at
    return document.created_at


def _encode_doc_cursor(value: str | datetime, row_id: uuid.UUID) -> str:
    raw = value.isoformat() if isinstance(value, datetime) else value
    return base64.urlsafe_b64encode(json.dumps([raw, str(row_id)]).encode()).decode().rstrip("=")


def _decode_doc_cursor(cursor: str, field: str) -> tuple[str | datetime, uuid.UUID]:
    try:
        raw, row_id = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        value = raw if field == "title" else datetime.fromisoformat(raw)
        return value, uuid.UUID(row_id)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ValidationFailed("The cursor is invalid.") from exc


async def list_documents(
    session: AsyncSession,
    ctx: RequestContext,
    kb_id: uuid.UUID,
    *,
    cursor: str | None,
    limit: int,
    status: DocumentStatus | None,
    document_type: str | None,
    classification: Classification | None,
    sort: str,
) -> Page[DocumentOut]:
    """Documents in a KB the caller can see, keyset-paginated on (sort value, id) so pages never
    repeat or skip rows that existed when paging started. The cursor is bound to `sort`."""
    kb, _ = await load_kb(session, ctx, kb_id)
    limit = page_limit(limit)
    descending, field = sort.startswith("-"), sort.lstrip("-")
    column = _sort_column(field)
    query = select(Document).where(
        Document.organization_id == ctx.organization_id,
        Document.knowledge_base_id == kb.id,
        Document.status != DocumentStatus.DELETED.value,  # deleted documents disappear entirely
    )
    if status is not None:
        query = query.where(Document.status == status.value)
    if document_type is not None:
        query = query.where(Document.document_type == document_type)
    if classification is not None:
        query = query.where(Document.classification == classification.value)
    if cursor is not None:
        value, row_id = _decode_doc_cursor(cursor, field)
        position = tuple_(column, Document.id)
        query = query.where(
            position < tuple_(value, row_id) if descending else position > tuple_(value, row_id)
        )
    order = (column.desc(), Document.id.desc()) if descending else (column, Document.id)
    documents = list(await session.scalars(query.order_by(*order).limit(limit + 1)))
    page = documents[:limit]
    states = await _latest_states(session, [d.id for d in page])
    next_cursor = None
    if len(documents) > limit:
        last = page[-1]
        next_cursor = _encode_doc_cursor(_sort_value(last, field), last.id)
    return Page[DocumentOut](
        items=[_document_out(d, states.get(d.id)) for d in page], next_cursor=next_cursor
    )


async def get_document(
    session: AsyncSession, ctx: RequestContext, document_id: uuid.UUID
) -> DocumentOut:
    document = await _visible_document(session, ctx, document_id)
    states = await _latest_states(session, [document.id])
    return _document_out(document, states.get(document.id))


async def list_versions(
    session: AsyncSession, ctx: RequestContext, document_id: uuid.UUID
) -> list[DocumentVersionOut]:
    document = await _visible_document(session, ctx, document_id)
    versions = await session.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.organization_id == ctx.organization_id,
            DocumentVersion.document_id == document.id,
        )
        .order_by(DocumentVersion.version_number.desc())
    )
    return [
        DocumentVersionOut(
            id=v.id,
            version_number=v.version_number,
            sha256=v.sha256,
            mime_type=v.mime_type,
            size_bytes=v.size_bytes,
            parser_name=v.parser_name,
            parser_version=v.parser_version,
            integrity_status=v.integrity_status,
            approval_status=ApprovalStatus(v.approval_status),
            ingestion_state=IngestionState(v.ingestion_status),
            effective_from=v.effective_from,
            effective_to=v.effective_to,
            created_at=v.created_at,
        )
        for v in versions
    ]


async def delete_document(
    session: AsyncSession, ctx: RequestContext, document_id: uuid.UUID
) -> None:
    """Archive now (immediately non-retrievable); the full deletion cascade is Session 49."""
    document = await _visible_document(session, ctx, document_id, lock=True)
    if document.status == DocumentStatus.ARCHIVED.value:
        return
    document.status = DocumentStatus.ARCHIVED.value
    document.archived_at = datetime.now(UTC)
    await audit.record(session, ctx, "document.archived", "document", document.id)


async def get_ingestion_job(
    session: AsyncSession, ctx: RequestContext, job_id: uuid.UUID
) -> IngestionJobOut:
    row = (
        await session.execute(
            select(IngestionJob, DocumentVersion.document_id)
            .join(DocumentVersion, DocumentVersion.id == IngestionJob.document_version_id)
            .where(IngestionJob.id == job_id, IngestionJob.organization_id == ctx.organization_id)
        )
    ).one_or_none()
    if row is None:
        raise NotFound("The ingestion job was not found.")
    job, document_id = row
    try:
        await _visible_document(session, ctx, document_id)
    except NotFound:
        raise NotFound("The ingestion job was not found.") from None
    return IngestionJobOut(
        id=job.id,
        document_id=document_id,
        document_version_id=job.document_version_id,
        state=IngestionState(job.state),
        stage=job.stage,
        progress_percent=job.progress_percent,
        attempt_count=job.attempt_count,
        error_code=job.error_code,
        error_detail_safe=job.error_detail_safe,
        retryable=job.state == IngestionState.FAILED_RETRYABLE.value,
        started_at=job.started_at,
        completed_at=job.completed_at,
        heartbeat_at=job.heartbeat_at,
    )
