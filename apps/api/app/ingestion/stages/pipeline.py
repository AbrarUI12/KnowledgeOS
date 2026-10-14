"""Real ingestion stages (S17-S19 T3.5; EMBEDDING → VERIFYING S22-S23 T4.2).

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
import functools
import hashlib
import io
import json
import math
import uuid
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import PurePath

from sqlalchemy import Float, delete, func, select, text, update
from sqlalchemy.dialects.postgresql import distinct_on

from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import (
    Chunk,
    DataSource,
    Document,
    DocumentVersion,
    IndexGeneration,
    IngestionJob,
    KnowledgeBase,
    Upload,
)
from app.db.text_search import fts_config
from app.domain.enums import IngestionState
from app.ingestion.canonical import CanonicalDocument
from app.ingestion.chunking.types import Chunker
from app.ingestion.errors import APPROVAL_HOLD, PermanentError, Quarantined, RetryableError
from app.ingestion.parsing.base import DocumentParser, ParserError
from app.ingestion.runner import Checkpoint, StageContext, StageFn
from app.providers.embeddings.base import EmbeddingProvider, EmbeddingUnavailableError
from app.providers.scanning.base import MalwareScanner, MalwareScanStatus
from app.providers.storage import (
    ObjectStore,
    ObjectStoreError,
    canonical_artifact_key,
    trusted_original_key,
)
from app.security.content_types import ContentScanner, ContentScanOutcome
from app.security.file_validation import ValidationConfig, ValidationStatus, validate_file
from app.services import chunk_acl

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
    # None: no embedding library installed. Local/test then skip vectors; elsewhere EMBEDDING
    # fails retryably until the provider is available (never another model, plan §25.2).
    embedder: EmbeddingProvider | None = None
    require_embeddings: bool = True


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
    return v.version.object_key == _trusted_key(v)


def _frozen_key(v: _Version) -> str:
    """Server-only quarantine key holding the exact bytes this version is validated, scanned and
    promoted from. No presigned URL is ever issued for it, so the uploader can't change it."""
    return f"{v.version.organization_id}/{v.kb.id}/{v.document.id}/{v.version.id}/frozen"


async def _freeze(deps: StageDeps, v: _Version) -> None:
    """Copy the uploaded object (still writable through its presigned PUT URL until it expires)
    to the frozen key, and point the version at it. Everything downstream reads the frozen
    copy, so bytes swapped in later via the upload URL are never scanned or promoted."""
    if v.version.object_key in (_frozen_key(v), _trusted_key(v)):
        return
    if not v.version.object_key:
        raise PermanentError("The uploaded file is missing.", code="original_missing")
    try:
        await deps.store.copy(
            deps.settings.s3_bucket_quarantine,
            v.version.object_key,
            deps.settings.s3_bucket_quarantine,
            _frozen_key(v),
        )
    except ObjectStoreError as exc:
        raise RetryableError("Object storage is unavailable.", code="storage_unavailable") from exc
    v.version.object_key = _frozen_key(v)


def _trusted_key(v: _Version) -> str:
    return trusted_original_key(v.version.organization_id, v.kb.id, v.document.id, v.version.id)


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
    """Freeze the upload, then run the frozen bytes through file-safety validation (S14) and
    record their sha256 and detected type, in the same transaction as the frozen `object_key`.
    Rejections end the job; flags (e.g. in-KB duplicate) travel on."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        await _freeze(deps, v)
        await ctx.session.flush()
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
    """ClamAV (T2.3) over the frozen bytes VALIDATING hashed. Infected → QUARANTINED (frozen copy
    kept for forensics). Clean → promote exactly those bytes to the trusted bucket; the
    quarantine copies are deleted only after this stage's transaction commits."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        if _is_trusted(v):
            return {"status": "clean", "promoted": True}  # already promoted before a crash
        if v.version.object_key != _frozen_key(v):
            raise PermanentError("The upload was never frozen.", code="integrity_unfrozen")
        data = await _original_bytes(deps, v)
        if hashlib.sha256(data).hexdigest() != v.version.sha256:
            raise PermanentError("The file changed after validation.", code="integrity_mismatch")
        result = await deps.malware_scanner.scan(io.BytesIO(data))
        if result.status is MalwareScanStatus.INFECTED:
            raise Quarantined("The file contains malware.", code="malware_detected")
        if result.status is MalwareScanStatus.ERROR:
            raise RetryableError("The malware scanner is unavailable.", code="scanner_unavailable")
        if result.status is MalwareScanStatus.SKIPPED and deps.settings.require_malware_scan:
            raise RetryableError(
                "Malware scanning is required but unavailable.", code="scan_required"
            )
        # The frozen key is server-only, so the copied bytes are the scanned bytes.
        await deps.store.copy(
            deps.settings.s3_bucket_quarantine,
            _frozen_key(v),
            deps.settings.s3_bucket_trusted,
            _trusted_key(v),
        )
        v.version.object_key = _trusted_key(v)
        upload_key = await ctx.session.scalar(
            select(Upload.object_key).where(Upload.document_version_id == v.version.id)
        )
        for key in (_frozen_key(v), upload_key):
            if key:
                ctx.after_commit.append(
                    functools.partial(deps.store.delete, deps.settings.s3_bucket_quarantine, key)
                )
        return {"status": result.status.value, "promoted": True, "sha256": v.version.sha256}

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
                    embedding_text_hash=hashlib.sha256(
                        draft.embedding_text.encode("utf-8")
                    ).hexdigest(),
                    identifiers=list(draft.identifiers),
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


async def _generation(ctx: StageContext, v: _Version) -> IndexGeneration | None:
    """The generation CHUNKING wrote into (recorded on the job), else the KB's active one."""
    generation_id = await ctx.session.scalar(
        select(IngestionJob.index_generation_id).where(IngestionJob.id == ctx.job_id)
    )
    generation_id = generation_id or v.kb.active_index_generation_id
    return await ctx.session.get(IndexGeneration, generation_id) if generation_id else None


def _vector_ok(vector: list[float], dimension: int) -> bool:
    return len(vector) == dimension and all(math.isfinite(x) for x in vector)


def embedding(deps: StageDeps) -> StageFn:
    """Embed child chunks that have no vector yet (resume-safe: a re-run embeds only what's
    missing). Vectors are reused from chunks of the same organization embedded by the same
    model with the same `embedding_text` (plan §13.1). The generation's recorded model and
    dimension must match the provider exactly; there is no fallback model (§25.2)."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        generation = await _generation(ctx, v)
        if generation is None:
            return {"embedded": 0, "reused": 0}
        rows = (
            await ctx.session.execute(
                select(Chunk.id, Chunk.embedding_text, Chunk.embedding_text_hash)
                .where(
                    Chunk.document_version_id == v.version.id,
                    Chunk.index_generation_id == generation.id,
                    Chunk.is_parent.is_(False),
                    Chunk.embedding.is_(None),
                )
                .order_by(Chunk.ordinal)
            )
        ).all()
        if not rows:
            return {"embedded": 0, "reused": 0}
        embedder = deps.embedder
        if embedder is None:
            if deps.require_embeddings:
                raise RetryableError(
                    "The embedding model isn't available.", code="embedding_unavailable"
                )
            return {"skipped": "no_embedding_provider", "chunks": len(rows)}
        if (embedder.model_id, embedder.dimension) != (
            generation.embedding_model,
            generation.embedding_dimension,
        ):
            raise PermanentError(
                "The configured embedding model doesn't match this index.",
                code="embedding_model_mismatch",
            )

        hashes = {
            r.id: r.embedding_text_hash or hashlib.sha256(r.embedding_text.encode()).hexdigest()
            for r in rows
        }
        reusable = dict(
            (
                await ctx.session.execute(
                    select(Chunk.embedding_text_hash, Chunk.embedding)
                    .join(IndexGeneration, IndexGeneration.id == Chunk.index_generation_id)
                    .where(
                        Chunk.organization_id == ctx.organization_id,
                        Chunk.embedding_text_hash.in_(set(hashes.values())),
                        Chunk.embedding.is_not(None),
                        IndexGeneration.embedding_model == generation.embedding_model,
                        IndexGeneration.embedding_dimension == generation.embedding_dimension,
                    )
                    .ext(distinct_on(Chunk.embedding_text_hash))
                )
            ).all()
        )
        vectors = {r.id: reusable[hashes[r.id]] for r in rows if hashes[r.id] in reusable}
        todo = [r for r in rows if r.id not in vectors]
        batch = max(1, min(embedder.max_batch, deps.settings.embedding_batch_size))
        for start in range(0, len(todo), batch):
            part = todo[start : start + batch]
            try:
                output = await embedder.embed_documents([r.embedding_text for r in part])
            except EmbeddingUnavailableError as exc:
                raise RetryableError(
                    "The embedding model isn't available.", code="embedding_unavailable"
                ) from exc
            except ValueError as exc:  # e.g. T4.1's EmbeddingDimensionError: configuration
                raise PermanentError(
                    "The embedding model returned malformed vectors.",
                    code="embedding_dimension_mismatch",
                ) from exc
            if len(output) != len(part) or not all(
                _vector_ok(vector, generation.embedding_dimension) for vector in output
            ):
                raise PermanentError(
                    "The embedding model returned malformed vectors.",
                    code="embedding_dimension_mismatch",
                )
            vectors.update({r.id: vector for r, vector in zip(part, output, strict=True)})
        await ctx.session.execute(
            update(Chunk),
            [
                {"id": chunk_id, "embedding": vector, "embedding_text_hash": hashes[chunk_id]}
                for chunk_id, vector in vectors.items()
            ],
        )
        return {
            "embedded": len(todo),
            "reused": len(rows) - len(todo),
            "model": generation.embedding_model,
        }

    return stage


# Title (A), section path (B) and body (C), each with the chunk's own configuration.
_SEARCH_VECTOR_SQL = text(
    """
    UPDATE chunks AS c SET
      fts_config = u.cfg::regconfig,
      search_vector =
        setweight(to_tsvector(u.cfg::regconfig, :title), 'A')
        || setweight(to_tsvector(u.cfg::regconfig, array_to_string(c.section_path, ' ')), 'B')
        || setweight(to_tsvector(u.cfg::regconfig, c.content), 'C')
    FROM unnest(CAST(:ids AS uuid[]), CAST(:configs AS text[])) AS u(id, cfg)
    WHERE c.id = u.id
    """
)


def indexing(deps: StageDeps) -> StageFn:
    """Full text (children) and ACL tokens (every chunk, parents included: context expansion is
    authorized the same way). The KB row is held shared while the ACL is read and written, so a
    concurrent ACL change waits and its `acl.changed` sync runs after this commits."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        generation = await _generation(ctx, v)
        if generation is None:
            return {"chunks": 0}
        scope = (
            Chunk.document_version_id == v.version.id,
            Chunk.index_generation_id == generation.id,
        )
        rows = (
            await ctx.session.execute(
                select(Chunk.id, Chunk.block_ids, Chunk.is_parent).where(*scope)
            )
        ).all()
        if not rows:
            return {"chunks": 0}
        principals = await chunk_acl.document_principals(
            ctx.session, ctx.organization_id, v.kb.id, v.document.id
        )
        await ctx.session.execute(update(Chunk).where(*scope).values(access_principals=principals))

        canonical = await _load_canonical(deps, v)
        block_language = {b.block_id: b.language for b in canonical.blocks if b.language}
        document_language = canonical.languages[0] if len(canonical.languages) == 1 else None
        configs: dict[uuid.UUID, str] = {}
        for row in rows:
            if row.is_parent:
                continue
            seen = Counter(block_language[b] for b in row.block_ids if b in block_language)
            language = seen.most_common(1)[0][0] if seen else document_language
            configs[row.id] = fts_config(language)
        if configs:
            await ctx.session.execute(
                _SEARCH_VECTOR_SQL,
                {
                    "ids": list(configs),
                    "configs": list(configs.values()),
                    "title": v.document.title or "",
                },
            )
        return {
            "chunks": len(rows),
            "principals": len(principals),
            "fts_configs": sorted(set(configs.values())),
        }

    return stage


def verifying(deps: StageDeps) -> StageFn:
    """Every child has full text (and a vector, when embeddings run), every chunk has ACL tokens,
    and a dense self-query finds a child's own vector. The runner then marks the version READY
    and activates it."""

    async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        v = await _load(ctx)
        generation = await _generation(ctx, v)
        if generation is None:
            return {"chunks": 0}
        scope = (
            Chunk.document_version_id == v.version.id,
            Chunk.index_generation_id == generation.id,
        )
        child = Chunk.is_parent.is_(False)
        counts = (
            await ctx.session.execute(
                select(
                    func.count(),
                    func.count().filter(child),
                    func.count().filter(child, Chunk.search_vector.is_(None)),
                    func.count().filter(child, Chunk.embedding.is_(None)),
                    func.count().filter(func.cardinality(Chunk.access_principals) == 0),
                ).where(*scope)
            )
        ).one()
        total, children, no_text, no_vector, no_acl = counts
        embeddings_expected = deps.embedder is not None or deps.require_embeddings
        if no_text or no_acl or (embeddings_expected and no_vector):
            raise PermanentError(
                "The document's index is incomplete; reindex it.", code="index_incomplete"
            )
        self_query = "skipped"
        if children and embeddings_expected:
            # Exact vector match through the HNSW index; a miss means the index can't serve it.
            await ctx.session.execute(text("SET LOCAL hnsw.ef_search = 100"))
            sample = (
                select(Chunk.embedding)
                .where(*scope, child)
                .order_by(Chunk.ordinal)
                .limit(1)
                .scalar_subquery()
            )
            cosine_distance = Chunk.embedding.op("<=>", return_type=Float)(sample)
            distance = await ctx.session.scalar(
                select(cosine_distance)
                .where(Chunk.index_generation_id == generation.id, Chunk.embedding.is_not(None))
                .order_by(cosine_distance)
                .limit(1)
            )
            if distance is None or distance > 1e-6:
                raise RetryableError(
                    "The vector index didn't return the document's own chunk.",
                    code="index_self_query_failed",
                )
            self_query = "ok"
        return {"chunks": total, "children": children, "self_query": self_query}

    return stage


def build_stages(
    deps: StageDeps, base: Mapping[IngestionState, StageFn]
) -> dict[IngestionState, StageFn]:
    """Every real stage over `base` (the stubs)."""
    return {
        **base,
        S.VALIDATING: validating(deps),
        S.MALWARE_SCAN: malware_scan(deps),
        S.PARSING: parsing(deps),
        S.NORMALIZING: normalizing(deps),
        S.SECURITY_SCAN: security_scan(deps),
        S.CHUNKING: chunking(deps),
        S.EMBEDDING: embedding(deps),
        S.INDEXING: indexing(deps),
        S.VERIFYING: verifying(deps),
    }
