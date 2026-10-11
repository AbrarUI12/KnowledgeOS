"""API schemas: knowledge bases, ACLs, uploads, documents, ingestion jobs (T1.0; implemented
T2.1/T2.4/T3.x)."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.domain.enums import (
    AclPermission,
    ApprovalStatus,
    Classification,
    DocumentStatus,
    IngestionState,
    PrincipalType,
    Visibility,
)
from app.ingestion.canonical import CanonicalDocument
from app.security.content_types import ContentFinding

# ----------------------------------------------------------------------------- knowledge bases


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    visibility: Visibility = Visibility.ORGANIZATION


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    visibility: Visibility | None = None


class KnowledgeBaseOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    visibility: Visibility
    document_count: int
    can_manage: bool = Field(description="Whether the caller may manage this KB (UI hint only)")
    created_at: datetime
    archived_at: datetime | None = None


class AclEntry(BaseModel):
    principal_type: PrincipalType
    principal_id: str = Field(description="User/group UUID, or a role key for principal_type=role")
    permission: AclPermission


class KnowledgeBasePermissions(BaseModel):
    entries: list[AclEntry]
    propagated_at: datetime | None = Field(
        default=None, description="When chunk ACLs last confirmed this state (Session 23)"
    )


class IndexGenerationOut(BaseModel):
    id: uuid.UUID
    generation_number: int
    status: str  # building | candidate | active | retired | failed
    embedding_provider: str
    embedding_model: str
    embedding_dimension: int
    chunker_name: str
    chunker_config: dict[str, Any]
    created_at: datetime
    activated_at: datetime | None = None


# ----------------------------------------------------------------------------- uploads


class UploadCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=512)
    content_type: str = Field(min_length=3, max_length=200)
    size_bytes: int = Field(gt=0)
    document_id: uuid.UUID | None = Field(
        default=None, description="Set to upload a new version of an existing document"
    )


class UploadOut(BaseModel):
    upload_id: uuid.UUID
    url: str = Field(description="Presigned URL to PUT the file to (quarantine bucket)")
    method: str = "PUT"
    headers: dict[str, str] = Field(default_factory=dict)
    expires_at: datetime


class UploadComplete(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    classification: Classification = Classification.INTERNAL


class UploadCompleted(BaseModel):
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    ingestion_job_id: uuid.UUID
    version_number: int


# ----------------------------------------------------------------------------- documents


class DocumentOut(BaseModel):
    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    title: str
    document_type: str | None
    classification: Classification
    status: DocumentStatus
    active_version_id: uuid.UUID | None
    latest_version_number: int
    ingestion_state: IngestionState | None = Field(
        default=None, description="State of the latest version's ingestion job"
    )
    created_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime | None = None


class DocumentVersionOut(BaseModel):
    id: uuid.UUID
    version_number: int
    sha256: str | None
    mime_type: str | None
    size_bytes: int | None
    parser_name: str | None
    parser_version: str | None
    integrity_status: str
    approval_status: ApprovalStatus
    ingestion_state: IngestionState
    effective_from: datetime | None = None
    effective_to: datetime | None = None
    created_at: datetime


class ApprovalDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class ContentUrl(BaseModel):
    url: str = Field(description="Short-lived signed URL to the trusted original")
    expires_at: datetime


class DocumentInspection(BaseModel):
    """Inspect mode (knowledge managers): canonical artifact + chunk boundaries + scan findings."""

    version: DocumentVersionOut
    canonical: CanonicalDocument | None
    chunks: list["ChunkSummary"]
    content_findings: list[ContentFinding] = Field(default_factory=list)


class ChunkSummary(BaseModel):
    id: uuid.UUID
    ordinal: int
    token_count: int
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    block_ids: list[str]


class ChunkContext(BaseModel):
    """A chunk plus its neighbors, authorization applied (evidence rail 'surrounding context')."""

    chunk: ChunkSummary
    content: str
    before: list[str] = Field(default_factory=list)
    after: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------------- ingestion jobs


class IngestionJobOut(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    state: IngestionState
    stage: str | None
    progress_percent: int = Field(ge=0, le=100)
    attempt_count: int
    error_code: str | None = None
    error_detail_safe: str | None = None
    retryable: bool = False
    trace_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    heartbeat_at: datetime | None = None


class IngestionJobEvent(BaseModel):
    at: datetime
    state: IngestionState
    stage: str | None
    message: str | None


DocumentInspection.model_rebuild()
