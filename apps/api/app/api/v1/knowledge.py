"""Knowledge base, upload, document and ingestion endpoints (contracts from T1.0; implemented in
T2.1,
T2.4, T3.5, T3.6, T4.2, T5.4)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.v1._stub import ERRORS, IdempotencyKeyHeader, OrgIdHeader, stub
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

router = APIRouter(responses=ERRORS)

Cursor = Annotated[str | None, Query(description="Opaque cursor from a previous page")]
Limit = Annotated[int, Query(ge=1, le=200)]

# ----------------------------------------------------------------------------- knowledge bases


@router.get("/knowledge-bases", tags=["knowledge_bases"], response_model=list[KnowledgeBaseOut])
async def list_knowledge_bases(org: OrgIdHeader) -> list[KnowledgeBaseOut]:
    """KBs the caller may query (restricted KBs without an ACL match are invisible)."""
    stub("T2.1")


@router.post(
    "/knowledge-bases",
    tags=["knowledge_bases"],
    response_model=KnowledgeBaseOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base(org: OrgIdHeader, body: KnowledgeBaseCreate) -> KnowledgeBaseOut:
    stub("T2.1")


@router.get("/knowledge-bases/{kb_id}", tags=["knowledge_bases"], response_model=KnowledgeBaseOut)
async def get_knowledge_base(org: OrgIdHeader, kb_id: uuid.UUID) -> KnowledgeBaseOut:
    stub("T2.1")


@router.patch("/knowledge-bases/{kb_id}", tags=["knowledge_bases"], response_model=KnowledgeBaseOut)
async def update_knowledge_base(
    org: OrgIdHeader, kb_id: uuid.UUID, body: KnowledgeBaseUpdate
) -> KnowledgeBaseOut:
    stub("T2.1")


@router.delete(
    "/knowledge-bases/{kb_id}",
    tags=["knowledge_bases"],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def archive_knowledge_base(org: OrgIdHeader, kb_id: uuid.UUID) -> None:
    """Archive (soft-delete); content stops being retrievable immediately."""
    stub("T2.1")


@router.get(
    "/knowledge-bases/{kb_id}/permissions",
    tags=["knowledge_bases"],
    response_model=KnowledgeBasePermissions,
)
async def get_knowledge_base_permissions(
    org: OrgIdHeader, kb_id: uuid.UUID
) -> KnowledgeBasePermissions:
    stub("T2.1")


@router.put(
    "/knowledge-bases/{kb_id}/permissions",
    tags=["knowledge_bases"],
    response_model=KnowledgeBasePermissions,
)
async def set_knowledge_base_permissions(
    org: OrgIdHeader, kb_id: uuid.UUID, body: KnowledgeBasePermissionsUpdate
) -> KnowledgeBasePermissions:
    """Replace the allow-only ACL (`kb.manage`). Emits `acl.changed`; chunks update
    asynchronously."""
    stub("T2.1")


@router.get(
    "/knowledge-bases/{kb_id}/index-generations",
    tags=["knowledge_bases"],
    response_model=list[IndexGenerationOut],
)
async def list_index_generations(org: OrgIdHeader, kb_id: uuid.UUID) -> list[IndexGenerationOut]:
    stub("T4.2")


# ----------------------------------------------------------------------------- uploads


@router.post(
    "/knowledge-bases/{kb_id}/uploads",
    tags=["uploads"],
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_upload(org: OrgIdHeader, kb_id: uuid.UUID, body: UploadCreate) -> UploadOut:
    """Start an upload (`document.upload`): returns a presigned PUT URL to the quarantine bucket."""
    stub("T2.4")


@router.post("/uploads/{upload_id}/complete", tags=["uploads"], response_model=UploadCompleted)
async def complete_upload(
    org: OrgIdHeader,
    upload_id: uuid.UUID,
    body: UploadComplete,
    idempotency_key: IdempotencyKeyHeader = None,
) -> UploadCompleted:
    """Verify the uploaded object and create document + version + ingestion job atomically.
    Supports `Idempotency-Key`."""
    stub("T2.4")


# ----------------------------------------------------------------------------- documents


@router.get(
    "/knowledge-bases/{kb_id}/documents", tags=["documents"], response_model=Page[DocumentOut]
)
async def list_documents(
    org: OrgIdHeader,
    kb_id: uuid.UUID,
    cursor: Cursor = None,
    limit: Limit = 50,
    status_filter: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    document_type: Annotated[str | None, Query(max_length=64)] = None,
    classification: Annotated[Classification | None, Query()] = None,
    sort: Annotated[str, Query(pattern=r"^-?(title|created_at|updated_at)$")] = "-updated_at",
) -> Page[DocumentOut]:
    stub("T2.4")


@router.get("/documents/{document_id}", tags=["documents"], response_model=DocumentOut)
async def get_document(org: OrgIdHeader, document_id: uuid.UUID) -> DocumentOut:
    stub("T2.4")


@router.delete(
    "/documents/{document_id}", tags=["documents"], status_code=status.HTTP_204_NO_CONTENT
)
async def delete_document(org: OrgIdHeader, document_id: uuid.UUID) -> None:
    """Mark non-retrievable immediately (`document.delete`); full cascade in Session 49."""
    stub("T2.4")


@router.get(
    "/documents/{document_id}/versions",
    tags=["documents"],
    response_model=list[DocumentVersionOut],
)
async def list_document_versions(
    org: OrgIdHeader, document_id: uuid.UUID
) -> list[DocumentVersionOut]:
    stub("T2.4")


@router.post(
    "/documents/{document_id}/versions",
    tags=["documents"],
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
)
async def start_document_replacement(
    org: OrgIdHeader, document_id: uuid.UUID, body: UploadCreate
) -> UploadOut:
    """Start uploading a new version of an existing document."""
    stub("T2.4")


@router.post(
    "/documents/{document_id}/versions/{version_id}/approve",
    tags=["documents"],
    response_model=DocumentVersionOut,
)
async def approve_document_version(
    org: OrgIdHeader, document_id: uuid.UUID, version_id: uuid.UUID, body: ApprovalDecision
) -> DocumentVersionOut:
    stub("T3.5")


@router.post(
    "/documents/{document_id}/versions/{version_id}/reject",
    tags=["documents"],
    response_model=DocumentVersionOut,
)
async def reject_document_version(
    org: OrgIdHeader, document_id: uuid.UUID, version_id: uuid.UUID, body: ApprovalDecision
) -> DocumentVersionOut:
    stub("T3.5")


@router.get(
    "/documents/{document_id}/versions/{version_id}/inspect",
    tags=["documents"],
    response_model=DocumentInspection,
)
async def inspect_document_version(
    org: OrgIdHeader, document_id: uuid.UUID, version_id: uuid.UUID
) -> DocumentInspection:
    """Canonical artifact, chunk boundaries and scan findings (`kb.manage`)."""
    stub("T3.6")


@router.get(
    "/documents/{document_id}/versions/{version_id}/content-url",
    tags=["documents"],
    response_model=ContentUrl,
)
async def get_document_content_url(
    org: OrgIdHeader, document_id: uuid.UUID, version_id: uuid.UUID
) -> ContentUrl:
    stub("T5.4")


@router.post(
    "/documents/{document_id}/reindex",
    tags=["documents"],
    response_model=IngestionJobOut,
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_document(org: OrgIdHeader, document_id: uuid.UUID) -> IngestionJobOut:
    stub("T3.6")


@router.get("/chunks/{chunk_id}/context", tags=["documents"], response_model=ChunkContext)
async def get_chunk_context(
    org: OrgIdHeader,
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
    kb_id: uuid.UUID,
    cursor: Cursor = None,
    limit: Limit = 50,
    state: Annotated[list[IngestionState] | None, Query()] = None,
) -> Page[IngestionJobOut]:
    stub("T3.6")


@router.get("/ingestion-jobs/{job_id}", tags=["ingestion"], response_model=IngestionJobOut)
async def get_ingestion_job(org: OrgIdHeader, job_id: uuid.UUID) -> IngestionJobOut:
    stub("T2.4")


@router.get(
    "/ingestion-jobs/{job_id}/events",
    tags=["ingestion"],
    response_model=list[IngestionJobEvent],
)
async def list_ingestion_job_events(org: OrgIdHeader, job_id: uuid.UUID) -> list[IngestionJobEvent]:
    stub("T3.6")


@router.post("/ingestion-jobs/{job_id}/retry", tags=["ingestion"], response_model=IngestionJobOut)
async def retry_ingestion_job(org: OrgIdHeader, job_id: uuid.UUID) -> IngestionJobOut:
    """Resume from the failed stage using checkpoints."""
    stub("T3.6")


@router.post("/ingestion-jobs/{job_id}/cancel", tags=["ingestion"], response_model=IngestionJobOut)
async def cancel_ingestion_job(org: OrgIdHeader, job_id: uuid.UUID) -> IngestionJobOut:
    stub("T3.6")
