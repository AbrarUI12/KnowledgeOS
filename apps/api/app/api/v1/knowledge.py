"""Knowledge base, upload, document and ingestion endpoints (contracts from T1.0; implemented in
T2.1, T2.4, T3.5, T3.6, T4.2, T5.4)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, status

from app.api.dependencies.storage import Storage
from app.api.dependencies.tenancy import OrgContext, require_permission
from app.api.v1._stub import ERRORS, IdempotencyKeyHeader, OrgIdHeader, stub
from app.auth.authorization import RequestContext
from app.auth.permissions import Permission
from app.db.session import DbSession
from app.domain.enums import Classification, DocumentStatus, IngestionState
from app.domain.schemas.common import Page
from app.domain.schemas.knowledge import (
    ApprovalDecision,
    ChunkContext,
    ContentUrl,
    DocumentInspection,
    DocumentOut,
    DocumentVersionOut,
    IndexGenerationOut,
    IngestionJobEvent,
    IngestionJobOut,
    KnowledgeBaseCreate,
    KnowledgeBaseOut,
    KnowledgeBasePermissions,
    KnowledgeBasePermissionsUpdate,
    KnowledgeBaseUpdate,
    UploadComplete,
    UploadCompleted,
    UploadCreate,
    UploadOut,
)
from app.services import documents, knowledge_bases

router = APIRouter(responses=ERRORS)

CreateKb = Annotated[RequestContext, require_permission(Permission.KB_CREATE)]
UploadDocuments = Annotated[RequestContext, require_permission(Permission.DOCUMENT_UPLOAD)]
DeleteDocuments = Annotated[RequestContext, require_permission(Permission.DOCUMENT_DELETE)]
PublishDocuments = Annotated[RequestContext, require_permission(Permission.DOCUMENT_PUBLISH)]

Cursor = Annotated[str | None, Query(description="Opaque cursor from a previous page")]
Limit = Annotated[int, Query(ge=1, le=200)]

# ----------------------------------------------------------------------------- knowledge bases


@router.get("/knowledge-bases", tags=["knowledge_bases"], response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(
    org: OrgIdHeader, ctx: OrgContext, session: DbSession
) -> list[KnowledgeBaseOut]:
    """Active KBs the caller may query or manage (restricted KBs without an ACL match are
    invisible)."""
    return await knowledge_bases.list_knowledge_bases(session, ctx)


@router.post(
    "/knowledge-bases",
    tags=["knowledge_bases"],
    response_model=KnowledgeBaseOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base(
    org: OrgIdHeader, ctx: CreateKb, session: DbSession, body: KnowledgeBaseCreate
) -> KnowledgeBaseOut:
    """Create a KB (`kb.create`). The creator gets a `manage` ACL entry; an upload source is
    created with it."""
    return await knowledge_bases.create_knowledge_base(session, ctx, body)


@router.get("/knowledge-bases/{kb_id}", tags=["knowledge_bases"], response_model=KnowledgeBaseOut)
async def get_knowledge_base(
    org: OrgIdHeader, ctx: OrgContext, session: DbSession, kb_id: uuid.UUID
) -> KnowledgeBaseOut:
    return await knowledge_bases.get_knowledge_base(session, ctx, kb_id)


@router.patch("/knowledge-bases/{kb_id}", tags=["knowledge_bases"], response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    org: OrgIdHeader,
    ctx: OrgContext,
    session: DbSession,
    kb_id: uuid.UUID,
    body: KnowledgeBaseUpdate,
) -> KnowledgeBaseOut:
    """Update (`kb.manage` or a `manage` ACL entry). A visibility change emits `acl.changed`."""
    return await knowledge_bases.update_knowledge_base(session, ctx, kb_id, body)


@router.delete(
    "/knowledge-bases/{kb_id}",
    tags=["knowledge_bases"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def archive_knowledge_base(
    org: OrgIdHeader, ctx: OrgContext, session: DbSession, kb_id: uuid.UUID
) -> None:
    """Archive (soft-delete); content stops being retrievable immediately."""
    await knowledge_bases.archive_knowledge_base(session, ctx, kb_id)


@router.get(
    "/knowledge-bases/{kb_id}/permissions",
    tags=["knowledge_bases"],
    response_model=KnowledgeBasePermissions,
)
async def get_knowledge_base_permissions(
    org: OrgIdHeader, ctx: OrgContext, session: DbSession, kb_id: uuid.UUID
) -> KnowledgeBasePermissions:
    return await knowledge_bases.get_permissions(session, ctx, kb_id)


@router.put(
    "/knowledge-bases/{kb_id}/permissions",
    tags=["knowledge_bases"],
    response_model=KnowledgeBasePermissions,
)
async def set_knowledge_base_permissions(
    org: OrgIdHeader,
    ctx: OrgContext,
    session: DbSession,
    kb_id: uuid.UUID,
    body: KnowledgeBasePermissionsUpdate,
) -> KnowledgeBasePermissions:
    """Replace the allow-only ACL (manage access). Principals must belong to the organization
    (422 `invalid_principal`). Emits `acl.changed`; chunks update asynchronously."""
    return await knowledge_bases.set_permissions(session, ctx, kb_id, body.entries)


@router.get(
    "/knowledge-bases/{kb_id}/index-generations",
    tags=["knowledge_bases"],
    response_model=list[IndexGenerationOut],
)
async def list_index_generations(
    org: OrgIdHeader, ctx: OrgContext, kb_id: uuid.UUID
) -> list[IndexGenerationOut]:
    stub("T4.2")


# ----------------------------------------------------------------------------- uploads


@router.post(
    "/knowledge-bases/{kb_id}/uploads",
    tags=["uploads"],
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload(
    request: Request,
    org: OrgIdHeader,
    ctx: UploadDocuments,
    session: DbSession,
    store: Storage,
    kb_id: uuid.UUID,
    body: UploadCreate,
) -> UploadOut:
    """Start an upload (`document.upload`): returns a presigned PUT URL to the quarantine bucket.
    422 `unsupported_file_type`, 413 `file_too_large`, 409 `kb_archived`."""
    return await documents.create_upload(
        session, ctx, store, request.app.state.settings, kb_id, body
    )


@router.post("/uploads/{upload_id}/complete", tags=["uploads"], response_model=UploadCompleted)
async def complete_upload(
    request: Request,
    org: OrgIdHeader,
    ctx: UploadDocuments,
    session: DbSession,
    store: Storage,
    upload_id: uuid.UUID,
    body: UploadComplete,
    idempotency_key: IdempotencyKeyHeader = None,
) -> UploadCompleted:
    """Verify the uploaded object and create document + version + ingestion job + outbox event
    atomically. Completing twice returns the same result (the upload itself is the idempotency
    key; `Idempotency-Key` is accepted for client uniformity). 409 `upload_not_received`,
    422 `size_mismatch`, 410 `upload_expired`."""
    return await documents.complete_upload(
        session, ctx, store, request.app.state.settings, upload_id, body
    )


# ----------------------------------------------------------------------------- documents


@router.get(
    "/knowledge-bases/{kb_id}/documents", tags=["documents"], response_model=Page[DocumentOut]
)
async def list_documents(
    org: OrgIdHeader,
    ctx: OrgContext,
    session: DbSession,
    kb_id: uuid.UUID,
    cursor: Cursor = None,
    limit: Limit = 50,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    document_type: Annotated[str | None, Query(max_length=64)] = None,
    classification: Annotated[Classification | None, Query()] = None,
    sort: Annotated[str, Query(pattern=r"^-?(title|created_at|updated_at)$")] = "-updated_at",
) -> Page[DocumentOut]:
    return await documents.list_documents(
        session,
        ctx,
        kb_id,
        cursor=cursor,
        limit=limit,
        status=status_filter,
        document_type=document_type,
        classification=classification,
        sort=sort,
    )


@router.get("/documents/{document_id}", tags=["documents"], response_model=DocumentOut)
async def get_document(
    org: OrgIdHeader, ctx: OrgContext, session: DbSession, document_id: uuid.UUID
) -> DocumentOut:
    return await documents.get_document(session, ctx, document_id)


@router.delete(
    "/documents/{document_id}", tags=["documents"], status_code=status.HTTP_204_NO_CONTENT
)
async def delete_document(
    org: OrgIdHeader, ctx: DeleteDocuments, session: DbSession, document_id: uuid.UUID
) -> None:
    """Mark non-retrievable immediately (`document.delete`); full cascade in Session 49."""
    await documents.delete_document(session, ctx, document_id)


@router.get(
    "/documents/{document_id}/versions",
    tags=["documents"],
    response_model=list[DocumentVersionOut],
)
async def list_document_versions(
    org: OrgIdHeader, ctx: OrgContext, session: DbSession, document_id: uuid.UUID
) -> list[DocumentVersionOut]:
    return await documents.list_versions(session, ctx, document_id)


@router.post(
    "/documents/{document_id}/versions",
    tags=["documents"],
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_document_replacement(
    request: Request,
    org: OrgIdHeader,
    ctx: UploadDocuments,
    session: DbSession,
    store: Storage,
    document_id: uuid.UUID,
    body: UploadCreate,
) -> UploadOut:
    """Start uploading a new version of an existing document (`document.upload`)."""
    return await documents.start_replacement(
        session, ctx, store, request.app.state.settings, document_id, body
    )


@router.post(
    "/documents/{document_id}/versions/{version_id}/approve",
    tags=["documents"],
    response_model=DocumentVersionOut,
)
async def approve_document_version(
    org: OrgIdHeader,
    ctx: PublishDocuments,
    session: DbSession,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ApprovalDecision,
) -> DocumentVersionOut:
    """Approve a version held for review (`document.publish`): ingestion resumes at chunking.
    409 unless the version is pending approval."""
    return await documents.decide_approval(
        session, ctx, document_id, version_id, approve=True, reason=body.reason
    )


@router.post(
    "/documents/{document_id}/versions/{version_id}/reject",
    tags=["documents"],
    response_model=DocumentVersionOut,
)
async def reject_document_version(
    org: OrgIdHeader,
    ctx: PublishDocuments,
    session: DbSession,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: ApprovalDecision,
) -> DocumentVersionOut:
    """Reject a version held for review (`document.publish`): its ingestion job is cancelled.
    409 unless the version is pending approval."""
    return await documents.decide_approval(
        session, ctx, document_id, version_id, approve=False, reason=body.reason
    )


@router.get(
    "/documents/{document_id}/versions/{version_id}/inspect",
    tags=["documents"],
    response_model=DocumentInspection,
)
async def inspect_document_version(
    org: OrgIdHeader, ctx: OrgContext, document_id: uuid.UUID, version_id: uuid.UUID
) -> DocumentInspection:
    """Canonical artifact, chunk boundaries and scan findings (`kb.manage`)."""
    stub("T3.6")


@router.get(
    "/documents/{document_id}/versions/{version_id}/content-url",
    tags=["documents"],
    response_model=ContentUrl,
)
async def get_document_content_url(
    org: OrgIdHeader, ctx: OrgContext, document_id: uuid.UUID, version_id: uuid.UUID
) -> ContentUrl:
    stub("T5.4")


@router.post(
    "/documents/{document_id}/reindex",
    tags=["documents"],
    response_model=IngestionJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_document(
    org: OrgIdHeader, ctx: OrgContext, document_id: uuid.UUID
) -> IngestionJobOut:
    stub("T3.6")


@router.get("/chunks/{chunk_id}/context", tags=["documents"], response_model=ChunkContext)
async def get_chunk_context(
    org: OrgIdHeader,
    ctx: OrgContext,
    chunk_id: uuid.UUID,
    before: Annotated[int, Query(ge=0, le=5)] = 1,
    after: Annotated[int, Query(ge=0, le=5)] = 1,
) -> ChunkContext:
    stub("T5.4")


# ----------------------------------------------------------------------------- ingestion jobs


@router.get(
    "/knowledge-bases/{kb_id}/ingestion-jobs",
    tags=["ingestion"],
    response_model=Page[IngestionJobOut],
)
async def list_ingestion_jobs(
    org: OrgIdHeader,
    ctx: OrgContext,
    kb_id: uuid.UUID,
    cursor: Cursor = None,
    limit: Limit = 50,
    state: Annotated[list[IngestionState] | None, Query()] = None,
) -> Page[IngestionJobOut]:
    stub("T3.6")


@router.get("/ingestion-jobs/{job_id}", tags=["ingestion"], response_model=IngestionJobOut)
async def get_ingestion_job(
    org: OrgIdHeader, ctx: OrgContext, session: DbSession, job_id: uuid.UUID
) -> IngestionJobOut:
    return await documents.get_ingestion_job(session, ctx, job_id)


@router.get(
    "/ingestion-jobs/{job_id}/events",
    tags=["ingestion"],
    response_model=list[IngestionJobEvent],
)
async def list_ingestion_job_events(
    org: OrgIdHeader, ctx: OrgContext, job_id: uuid.UUID
) -> list[IngestionJobEvent]:
    stub("T3.6")


@router.post("/ingestion-jobs/{job_id}/retry", tags=["ingestion"], response_model=IngestionJobOut)
async def retry_ingestion_job(
    org: OrgIdHeader, ctx: OrgContext, job_id: uuid.UUID
) -> IngestionJobOut:
    """Resume from the failed stage using checkpoints."""
    stub("T3.6")


@router.post("/ingestion-jobs/{job_id}/cancel", tags=["ingestion"], response_model=IngestionJobOut)
async def cancel_ingestion_job(
    org: OrgIdHeader, ctx: OrgContext, job_id: uuid.UUID
) -> IngestionJobOut:
    stub("T3.6")
