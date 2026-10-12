"""Real ingestion stages up to CHUNKING (S17-S19, T3.5).

Each stage is `async (ctx, checkpoint) -> checkpoint`, runs inside the runner's work transaction
(tenant context set, advisory lock held) and must be idempotent: it can run again after a crash
that happened before its checkpoint was stored. Libraries (parser, normalizer, content scanner,
chunker) come in through `StageDeps`, so this module holds the orchestration only and stays
DB-aware while the libraries stay DB-free (docs/AGENT_WORKFLOW.md §4).

Object locations: before MALWARE_SCAN the original is in the quarantine bucket under
`version.object_key`; a clean scan copies it to the trusted bucket and `object_key` switches to
the trusted key. Infected files stay in quarantine for forensics.
"""

import asyncio
import io
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import delete, select

from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import (
    Chunk,
    DataSource,
    Document,
    DocumentVersion,
    IngestionJob,
    KnowledgeBase,
    Upload,
)
from app.domain.enums import IngestionState
from app.ingestion.canonical import CanonicalDocument
from app.ingestion.chunking.types import Chunker
from app.ingestion.errors import APPROVAL_HOLD, PermanentError, Quarantined, RetryableError
from app.ingestion.parsing.base import DocumentParser, ParserError
from app.ingestion.runner import Checkpoint, StageContext, StageFn
from app.providers.scanning.base import MalwareScanner, MalwareScanStatus
from app.providers.storage import (
    ObjectStore,
    ObjectStoreError,
    canonical_artifact_key,
    trusted_original_key,
)
from app.security.content_types import ContentScanner, ContentScanOutcome
from app.security.file_validation import ValidationConfig, ValidationStatus, validate_file

S = IngestionState
Normalizer = Callable[[CanonicalDocument], CanonicalDocument]

# Sources whose content always needs a knowledge manager's approval (plan §9.3, S19).
APPROVAL_TRUST_LEVELS = frozenset({"untrusted", "high_risk"})

MAX_CANONICAL_BYTES = 256 * 1024 * 1024  # canonical.json read limit


@dataclass(frozen=True, slots=True)
class StageDeps:
    settings: Settings
    store: ObjectStore
    malware_scanner: MalwareScanner
    parsers: tuple[DocumentParser, ...]
    normalize: Normalizer
    content_scanner: ContentScanner
    chunker: Chunker
    approve_flagged_content: bool = True  # flagged content waits for approval (policy default)


@dataclass(frozen=True, slots=True)
class _Version:
    version: DocumentVersion
    document: Document
    kb: KnowledgeBase


async def _load(ctx: StageContext) -> _Version:
    row = (
        await ctx.session.execute(
            select(DocumentVersion, Document, KnowledgeBase)
            .join(Document, Document.id == DocumentVersion.document_id)
            .join(KnowledgeBase, KnowledgeBase.id == Document.knowledge_base_id)
            .where(DocumentVersion.id == ctx.document_version_id)
        )
    ).one()
    return _Version(*row)


def _is_trusted(v: _Version) -> bool:
    return v.version.object_key == trusted_original_key(
        v.version.organization_id, v.kb.id, v.document.id, v.version.id
    )


async def _original_bytes(deps: StageDeps, v: _Version) -> bytes:
    bucket = (
        deps.settings.s3_bucket_trusted if _is_trusted(v) else deps.settings.s3_bucket_quarantine
    )
    if not v.version.object_key:
        raise PermanentError("The uploaded file is missing.", code="original_missing")
    try:
        return await deps.store.get_bytes(
            bucket, v.version.object_key, max_bytes=deps.settings.upload_max_bytes + 1
        )
    except ObjectStoreError as exc:
        raise RetryableError("Object storage is unavailable.", code="storage_unavailable") from exc


async def _load_canonical(deps: StageDeps, v: _Version) -> CanonicalDocument:
    if not v.version.canonical_artifact_key:
        raise PermanentError("The parsed document is missing.", code="canonical_missing")
    data = await deps.store.get_bytes(
        deps.settings.s3_bucket_artifacts,
        v.version.canonical_artifact_key,
        max_bytes=MAX_CANONICAL_BYTES,
    )
    return CanonicalDocument.model_validate_json(data)


async def _save_canonical(deps: StageDeps, v: _Version, document: CanonicalDocument) -> str:
    key = canonical_artifact_key(v.version.organization_id, v.kb.id, v.document.id, v.version.id)
    await deps.store.put(
        deps.settings.s3_bucket_artifacts,
        key,
        document.model_dump_json().encode(),
        content_type="application/json",
    )
    return key


# --------------------------------------------------------------------------- stages


def validating(deps: StageDeps) -> StageFn:
    """Stream the quarantined original through file-safety validation (S14); record its sha256
    and detected type. Rejections end the job; flags (e.g. in-KB duplicate) travel on."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        data = await _original_bytes(deps, v)
        filename = (
            await ctx.session.scalar(
                select(Upload.filename).where(Upload.document_version_id == v.version.id)
            )
            or f"document{PurePath(v.version.object_key or '').suffix}"
        )
        existing: set[str] = {
            sha
            for sha in await ctx.session.scalars(
                select(DocumentVersion.sha256)
                .join(Document, Document.id == DocumentVersion.document_id)
                .where(
                    Document.knowledge_base_id == v.kb.id,
                    DocumentVersion.id != v.version.id,
                    DocumentVersion.sha256.is_not(None),
                )
            )
            if sha
        }
        result = await asyncio.to_thread(
            validate_file,
            io.BytesIO(data),
            filename,
            config=ValidationConfig(max_file_bytes=deps.settings.upload_max_bytes),
            existing_sha256s_in_kb=existing,
        )
        v.version.sha256 = result.sha256
        if result.status is ValidationStatus.REJECTED:
            v.version.integrity_status = "failed"
            reason = result.reasons[0].value if result.reasons else "rejected"
            raise PermanentError("The file failed safety validation.", code=f"validation_{reason}")
        v.version.integrity_status = "verified"
        if result.detected_mime:
            v.version.mime_type = result.detected_mime
        return {
            "sha256": result.sha256,
            "detected_mime": result.detected_mime,
            "flags": [r.value for r in result.reasons],
        }

    return stage


def malware_scan(deps: StageDeps) -> StageFn:
    """ClamAV (T2.3). Infected → QUARANTINED (original kept in quarantine). Clean → promote the
    original to the trusted bucket and drop the quarantine copy."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        trusted_key = trusted_original_key(
            v.version.organization_id, v.kb.id, v.document.id, v.version.id
        )
        if _is_trusted(v):
            return {"status": "clean", "promoted": True}  # already promoted before a crash
        data = await _original_bytes(deps, v)
        result = await deps.malware_scanner.scan(io.BytesIO(data))
        if result.status is MalwareScanStatus.INFECTED:
            raise Quarantined("The file contains malware.", code="malware_detected")
        if result.status is MalwareScanStatus.ERROR:
            raise RetryableError("The malware scanner is unavailable.", code="scanner_unavailable")
        if result.status is MalwareScanStatus.SKIPPED and deps.settings.require_malware_scan:
            raise RetryableError(
                "Malware scanning is required but unavailable.", code="scan_required"
            )
        quarantine_key = v.version.object_key
        assert quarantine_key is not None  # noqa: S101 (checked by _original_bytes)
        await deps.store.copy(
            deps.settings.s3_bucket_quarantine,
            quarantine_key,
            deps.settings.s3_bucket_trusted,
            trusted_key,
        )
        v.version.object_key = trusted_key
        await ctx.session.flush()
        await deps.store.delete(deps.settings.s3_bucket_quarantine, quarantine_key)
        return {"status": result.status.value, "promoted": True}

    return stage


def parsing(deps: StageDeps) -> StageFn:
    """Original → CanonicalDocument (parser library, run off the event loop) → canonical.json in
    the artifacts bucket. Overwriting the same key makes a re-run harmless."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        mime = v.version.mime_type or "application/octet-stream"
        parser = next((p for p in deps.parsers if p.supports(mime)), None)
        if parser is None:
            raise PermanentError("This document format can't be parsed.", code="unsupported_format")
        data = await _original_bytes(deps, v)
        filename = (
            await ctx.session.scalar(
                select(Upload.filename).where(Upload.document_version_id == v.version.id)
            )
            or v.document.title
        )
        try:
            document = await asyncio.to_thread(
                parser.parse, data, filename=filename, mime_type=mime
            )
        except ParserError as exc:
            if exc.retryable:
                raise RetryableError("Document parsing timed out.", code=exc.code) from exc
            raise PermanentError("The document couldn't be parsed.", code=exc.code) from exc
        key = await _save_canonical(deps, v, document)
        v.version.canonical_artifact_key = key
        v.version.parser_name = parser.name
        v.version.parser_version = parser.version
        return {"artifact_key": key, "blocks": len(document.blocks), "parser": parser.name}

    return stage


def normalizing(deps: StageDeps) -> StageFn:
    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        document = await asyncio.to_thread(deps.normalize, await _load_canonical(deps, v))
        await _save_canonical(deps, v, document)
        return {"blocks": len(document.blocks)}

    return stage


def security_scan(deps: StageDeps) -> StageFn:
    """Content-security scan (S19). Findings are stored as rule + block ids only, never text.
    rejected → FAILED_PERMANENT, quarantined → QUARANTINED, flagged or an untrusted source →
    PENDING_APPROVAL (approval resumes at CHUNKING)."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        result = await asyncio.to_thread(deps.content_scanner.scan, await _load_canonical(deps, v))
        if result.outcome is ContentScanOutcome.REJECTED:
            raise PermanentError(
                "The document's content was rejected by policy.", code="content_rejected"
            )
        if result.outcome is ContentScanOutcome.QUARANTINED:
            raise Quarantined(
                "The document's content was quarantined by policy.", code="content_quarantined"
            )
        trust = await ctx.session.scalar(
            select(DataSource.trust_level).where(DataSource.id == v.document.source_id)
        )
        needs_approval = trust in APPROVAL_TRUST_LEVELS or (
            result.outcome is ContentScanOutcome.FLAGGED and deps.approve_flagged_content
        )
        findings = [
            {"rule_id": f.rule_id, "severity": f.severity, "block_ids": list(f.block_ids)}
            for f in result.findings
        ]
        checkpoint_out: Checkpoint = {
            "outcome": result.outcome.value,
            "score": result.score,
            "rules_version": result.rules_version,
            "findings": findings,
        }
        if needs_approval:
            checkpoint_out["hold"] = APPROVAL_HOLD
        return checkpoint_out

    return stage


def chunking(deps: StageDeps) -> StageFn:
    """Canonical blocks → chunks for the KB's active index generation. Delete-then-insert for
    (version, generation) inside the work transaction, so a re-run never duplicates rows."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        generation_id = v.kb.active_index_generation_id
        if generation_id is None:
            raise PermanentError("The knowledge base has no active index.", code="no_active_index")
        drafts = await asyncio.to_thread(deps.chunker.chunk, await _load_canonical(deps, v))
        await ctx.session.execute(
            delete(Chunk).where(
                Chunk.document_version_id == v.version.id,
                Chunk.index_generation_id == generation_id,
            )
        )
        ids = {draft.ordinal: new_uuid() for draft in drafts}
        # Parents first so child foreign keys resolve within the transaction.
        for draft in sorted(drafts, key=lambda d: (not d.is_parent, d.ordinal)):
            ctx.session.add(
                Chunk(
                    id=ids[draft.ordinal],
                    organization_id=ctx.organization_id,
                    knowledge_base_id=v.kb.id,
                    document_id=v.document.id,
                    document_version_id=v.version.id,
                    index_generation_id=generation_id,
                    ordinal=draft.ordinal,
                    parent_chunk_id=ids.get(draft.parent_ordinal)
                    if draft.parent_ordinal is not None
                    else None,
                    is_parent=draft.is_parent,
                    block_type=draft.block_type.value,
                    section_path=list(draft.section_path),
                    block_ids=list(draft.block_ids),
                    content=draft.content,
                    embedding_text=draft.embedding_text,
                    content_hash=draft.content_hash,
                    token_count=draft.token_count,
                    page_start=draft.location.page_start,
                    page_end=draft.location.page_end,
                    location_json=json.loads(draft.location.model_dump_json()),
                    metadata_json=draft.metadata,
                )
            )
            await ctx.session.flush()
        job = await ctx.session.get(IngestionJob, ctx.job_id)
        if job is not None:
            job.index_generation_id = generation_id
        return {
            "chunks": len(drafts),
            "index_generation_id": str(generation_id),
            "chunker": deps.chunker.config.name,
        }

    return stage


def build_stages(
    deps: StageDeps, base: Mapping[IngestionState, StageFn]
) -> dict[IngestionState, StageFn]:
    """The real stages through CHUNKING over `base` (EMBEDDING/INDEXING/VERIFYING stay as given
    until T4.2)."""
    return {
        **base,
        S.VALIDATING: validating(deps),
        S.MALWARE_SCAN: malware_scan(deps),
        S.PARSING: parsing(deps),
        S.NORMALIZING: normalizing(deps),
        S.SECURITY_SCAN: security_scan(deps),
        S.CHUNKING: chunking(deps),
    }
