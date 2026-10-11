"""Fake implementations of the T1.0 contracts (see tests/fakes/__init__.py)."""

import hashlib
import math
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import BinaryIO

from app.ingestion.canonical import Block, BlockType, CanonicalDocument, SourceLocation
from app.ingestion.chunking.types import ChunkDraft, ChunkerConfig
from app.providers.identity.base import TokenInvalidError, VerifiedToken
from app.providers.llm.base import ChatMessage, GenerationParams, LLMChunk, LLMResult
from app.providers.scanning.base import MalwareScanResult, MalwareScanStatus
from app.providers.search.base import (
    HybridSearchRequest,
    HybridSearchResult,
    QueryFilters,
    SearchScope,
)
from app.providers.storage.base import ObjectInfo, ObjectStoreError, PresignedUpload
from app.rag.types import Candidate, RankedHit, Usage
from app.security.content_types import (
    ContentFinding,
    ContentScanOutcome,
    ContentScanResult,
)

_WORD = re.compile(r"\w+", re.UNICODE)


def sha256_hex(data: bytes | str) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return hashlib.sha256(raw).hexdigest()


# ----------------------------------------------------------------------------- storage


class FakeObjectStore:
    def __init__(self, public_base_url: str = "http://fake-storage.test") -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, str]] = {}
        self.public_base_url = public_base_url

    async def presign_put(
        self, bucket: str, key: str, *, content_type: str, expires_in_seconds: int = 900
    ) -> PresignedUpload:
        return PresignedUpload(
            url=f"{self.public_base_url}/{bucket}/{key}?signature=fake",
            headers={"Content-Type": content_type},
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in_seconds),
        )

    async def head(self, bucket: str, key: str) -> ObjectInfo | None:
        if (bucket, key) not in self.objects:
            return None
        data, content_type = self.objects[(bucket, key)]
        return ObjectInfo(bucket=bucket, key=key, size_bytes=len(data), content_type=content_type)

    async def get_stream(
        self, bucket: str, key: str, *, chunk_size: int = 1024 * 1024
    ) -> AsyncIterator[bytes]:
        data = await self.get_bytes(bucket, key, max_bytes=2**62)
        for start in range(0, len(data), chunk_size):
            yield data[start : start + chunk_size]

    async def get_bytes(self, bucket: str, key: str, *, max_bytes: int) -> bytes:
        if (bucket, key) not in self.objects:
            raise ObjectStoreError(f"missing object {bucket}/{key}")
        data = self.objects[(bucket, key)][0]
        if len(data) > max_bytes:
            raise ObjectStoreError("object larger than max_bytes")
        return data

    async def put(self, bucket: str, key: str, data: bytes, *, content_type: str) -> ObjectInfo:
        self.objects[(bucket, key)] = (data, content_type)
        return ObjectInfo(bucket=bucket, key=key, size_bytes=len(data), content_type=content_type)

    async def copy(self, src_bucket: str, src_key: str, dst_bucket: str, dst_key: str) -> None:
        if (src_bucket, src_key) not in self.objects:
            raise ObjectStoreError("missing source object")
        self.objects[(dst_bucket, dst_key)] = self.objects[(src_bucket, src_key)]

    async def delete(self, bucket: str, key: str) -> None:
        self.objects.pop((bucket, key), None)

    async def exists(self, bucket: str, key: str) -> bool:
        return (bucket, key) in self.objects


# ----------------------------------------------------------------------- scanning


class FakeMalwareScanner:
    """Implements T2.3's `MalwareScanner`: INFECTED when the stream contains `marker`.

    Never uses the real EICAR string (Windows Defender deletes files containing it).
    """

    def __init__(self, marker: bytes = b"KOS-FAKE-MALWARE") -> None:
        self.marker = marker

    async def scan(self, stream: BinaryIO) -> MalwareScanResult:
        if self.marker in stream.read():
            return MalwareScanResult(status=MalwareScanStatus.INFECTED, threat="Fake.Test")
        return MalwareScanResult(status=MalwareScanStatus.CLEAN)


class FakeContentScanner:
    """Flags blocks containing obvious injection phrases."""

    PHRASES = ("ignore previous instructions", "ignore all previous instructions")

    def scan(self, document: CanonicalDocument) -> ContentScanResult:
        hits = tuple(
            b.block_id for b in document.blocks if any(p in b.text.lower() for p in self.PHRASES)
        )
        if not hits:
            return ContentScanResult(
                outcome=ContentScanOutcome.CLEAN, score=0.0, rules_version="fake"
            )
        finding = ContentFinding(rule_id="injection.ignore_previous", severity=4, block_ids=hits)
        return ContentScanResult(
            outcome=ContentScanOutcome.FLAGGED,
            score=4.0,
            findings=(finding,),
            rules_version="fake",
        )


# ----------------------------------------------------------------------------- parsing / chunking


class FakeParser:
    """UTF-8 text: '# ' lines become headings; blank-line-separated text becomes paragraphs."""

    @property
    def name(self) -> str:
        return "fake-text"

    @property
    def version(self) -> str:
        return "1"

    def supports(self, mime_type: str) -> bool:
        return mime_type in {"text/plain", "text/markdown"}

    def parse(self, data: bytes, *, filename: str, mime_type: str) -> CanonicalDocument:
        text = data.decode("utf-8")
        blocks: list[Block] = []
        headings: list[str] = []
        for order, part in enumerate(p.strip() for p in text.split("\n\n")):
            if not part:
                continue
            if part.startswith("# "):
                title = part[2:].strip()
                headings = [title]
                block_type, body = BlockType.HEADING, title
            else:
                block_type, body = BlockType.PARAGRAPH, part
            blocks.append(
                Block(
                    block_id=sha256_hex(f"{order}:{body}")[:16],
                    type=block_type,
                    text=body,
                    heading_level=1 if block_type is BlockType.HEADING else None,
                    heading_path=[] if block_type is BlockType.HEADING else list(headings),
                    source_order=order,
                    page=1,
                )
            )
        return CanonicalDocument(
            title=headings[0] if headings else filename,
            mime_type=mime_type,
            page_count=1,
            blocks=blocks,
            parser_name=self.name,
            parser_version=self.version,
        )


class FakeChunker:
    """One chunk per non-furniture, non-heading block (no token-size logic)."""

    def __init__(self) -> None:
        self._config = ChunkerConfig(name="fake", version="1")

    @property
    def config(self) -> ChunkerConfig:
        return self._config

    def chunk(self, document: CanonicalDocument) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        for block in document.blocks:
            if block.type in (BlockType.FURNITURE, BlockType.HEADING) or not block.text:
                continue
            section = " > ".join(block.heading_path)
            drafts.append(
                ChunkDraft(
                    ordinal=len(drafts),
                    block_type=block.type,
                    block_ids=[block.block_id],
                    section_path=list(block.heading_path),
                    content=block.text,
                    embedding_text=f"{document.title}\n{section}\n{block.text}".strip(),
                    content_hash=sha256_hex(block.text),
                    token_count=len(_WORD.findall(block.text)),
                    location=SourceLocation(page_start=block.page, page_end=block.page),
                )
            )
        return drafts


# ----------------------------------------------------------------------------- models


class FakeEmbeddingProvider:
    """Deterministic bag-of-words hashing into `dimension` buckets, L2-normalized.

    Texts sharing words get positive cosine similarity, which is enough for retrieval tests.
    """

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension

    provider_id = "fake"
    model_id = "fake-hash-embedding-v1"
    normalized = True
    max_batch = 64
    is_external = False

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        for word in _WORD.findall(text.lower()):
            bucket = int(sha256_hex(word)[:8], 16) % self._dimension
            vec[bucket] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(t) for t in texts]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(text)


class FakeReranker:
    """Score = fraction of query words present in the passage."""

    model_id = "fake-overlap-reranker"
    is_external = False

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        words = set(_WORD.findall(query.lower()))
        if not words:
            return [0.0 for _ in passages]
        return [len(words & set(_WORD.findall(p.lower()))) / len(words) for p in passages]


class FakeLLM:
    """Returns scripted replies in order (the last one repeats). Streams sentence by sentence."""

    def __init__(
        self, replies: Sequence[str] = ("I don't have enough evidence to answer.",)
    ) -> None:
        self.replies = list(replies)
        self.calls: list[list[ChatMessage]] = []

    provider_id = "fake"
    model_id = "fake-llm"
    is_external = False

    def _next(self, messages: Sequence[ChatMessage]) -> str:
        self.calls.append(list(messages))
        index = min(len(self.calls) - 1, len(self.replies) - 1)
        return self.replies[index]

    @staticmethod
    def _usage(messages: Sequence[ChatMessage], text: str) -> Usage:
        prompt_words = sum(len(_WORD.findall(m.content)) for m in messages)
        return Usage(
            input_tokens=prompt_words, output_tokens=len(_WORD.findall(text)), estimated=True
        )

    async def generate(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> LLMResult:
        text = self._next(messages)
        return LLMResult(
            text=text,
            model=self.model_id,
            provider=self.provider_id,
            finish_reason="stop",
            usage=self._usage(messages, text),
        )

    async def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> AsyncIterator[LLMChunk]:
        text = self._next(messages)
        for sentence in re.findall(r"[^.!?]+[.!?]?\s*", text):
            yield LLMChunk(delta=sentence)
        yield LLMChunk(finish_reason="stop", usage=self._usage(messages, text))


# ----------------------------------------------------------------------------- search / identity


@dataclass
class IndexedChunk:
    candidate: Candidate
    organization_id: uuid.UUID
    access_principals: frozenset[str]
    embedding: list[float] = field(default_factory=list)
    source_id: uuid.UUID | None = None
    document_type: str | None = None
    tags: frozenset[str] = frozenset()
    department: str | None = None
    language: str | None = None
    modified_on: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None


def _matches(chunk: IndexedChunk, f: QueryFilters) -> bool:
    checks = (
        not f.document_ids or chunk.candidate.document_id in f.document_ids,
        not f.source_ids or chunk.source_id in f.source_ids,
        not f.document_types or chunk.document_type in f.document_types,
        not f.tags or set(f.tags) <= chunk.tags,
        f.department is None or chunk.department == f.department,
        not f.languages or chunk.language in f.languages,
        not f.modified_from
        or (chunk.modified_on is not None and chunk.modified_on >= f.modified_from),
        not f.modified_to or (chunk.modified_on is not None and chunk.modified_on <= f.modified_to),
        not f.effective_from
        or chunk.effective_to is None
        or chunk.effective_to >= f.effective_from,
        not f.effective_to
        or chunk.effective_from is None
        or chunk.effective_from <= f.effective_to,
    )
    return all(checks)


class FakeSearchBackend:
    """In-memory search that applies the authorization scope **and** QueryFilters, like the real
    backend must (filters narrow the authorized pool; they never widen it)."""

    def __init__(self, chunks: Sequence[IndexedChunk] = (), generation_id: uuid.UUID | None = None):
        self.chunks = list(chunks)
        self.generation_id = generation_id or uuid.uuid4()

    def _authorized(self, scope: SearchScope) -> list[IndexedChunk]:
        return [
            c
            for c in self.chunks
            if c.organization_id == scope.organization_id
            and c.candidate.knowledge_base_id in scope.knowledge_base_ids
            and c.access_principals & set(scope.principal_tokens)
        ]

    def _pool(self, request: HybridSearchRequest) -> list[IndexedChunk]:
        return [c for c in self._authorized(request.scope) if _matches(c, request.filters)]

    async def dense_search(self, request: HybridSearchRequest) -> list[RankedHit]:
        if request.query_embedding is None:
            return []
        q = request.query_embedding
        scored = [
            (sum(a * b for a, b in zip(q, c.embedding, strict=False)), c)
            for c in self._pool(request)
        ]
        ranked = [(s, c) for s, c in sorted(scored, key=lambda x: -x[0]) if s > 0]
        return [
            RankedHit(candidate=c.candidate, dense_rank=i + 1, dense_score=s)
            for i, (s, c) in enumerate(ranked[: request.dense_k])
        ]

    async def lexical_search(self, request: HybridSearchRequest) -> list[RankedHit]:
        words = set(_WORD.findall(request.query.lower()))
        scored = [
            (len(words & set(_WORD.findall(c.candidate.content.lower()))), c)
            for c in self._pool(request)
        ]
        ranked = [(s, c) for s, c in sorted(scored, key=lambda x: -x[0]) if s > 0]
        return [
            RankedHit(candidate=c.candidate, lexical_rank=i + 1, lexical_score=float(s))
            for i, (s, c) in enumerate(ranked[: request.lexical_k])
        ]

    async def hybrid_search(self, request: HybridSearchRequest) -> HybridSearchResult:
        return HybridSearchResult(
            dense=await self.dense_search(request),
            lexical=await self.lexical_search(request),
            index_generation_id=self.generation_id,
        )

    async def neighbors(
        self, scope: SearchScope, chunk_id: uuid.UUID, *, before: int = 1, after: int = 1
    ) -> list[RankedHit]:
        pool = self._authorized(scope)
        target = next((c for c in pool if c.candidate.chunk_id == chunk_id), None)
        if target is None:
            return []
        version = target.candidate.document_version_id
        lo, hi = target.candidate.ordinal - before, target.candidate.ordinal + after
        return [
            RankedHit(candidate=c.candidate)
            for c in sorted(pool, key=lambda c: c.candidate.ordinal)
            if c.candidate.document_version_id == version
            and lo <= c.candidate.ordinal <= hi
            and c.candidate.chunk_id != chunk_id
        ]


class FakeIdentityVerifier:
    def __init__(self, tokens: dict[str, VerifiedToken] | None = None) -> None:
        self.tokens = dict(tokens or {})

    async def verify(self, token: str) -> VerifiedToken:
        try:
            return self.tokens[token]
        except KeyError:
            raise TokenInvalidError("unknown token") from None
