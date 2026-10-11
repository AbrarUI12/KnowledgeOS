"""Contract: chunking (plan §12, T1.0). Implementations: Codex T3.4 (structure-aware,
recursive_fixed).

Chunkers are pure: `CanonicalDocument` in, ordered `ChunkDraft`s out, no database. The CHUNKING
stage
(Claude, T3.5) persists drafts as `chunks` rows for a (document_version, index_generation) pair and
adds tenant, ACL and generation columns. Output must be deterministic for identical input + config.
"""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.ingestion.canonical import SHA256_PATTERN, BlockType, CanonicalDocument, SourceLocation


class ChunkerConfig(BaseModel):
    """Recorded on the index generation (plan §12.2 rule 8). Defaults from plan §12.1."""

    model_config = ConfigDict(frozen=True)

    name: str = "structure_aware"
    version: str = "1"
    target_tokens: int = 600
    overlap_tokens: int = 80
    min_tokens: int = 80
    parent_min_tokens: int = 1500
    parent_max_tokens: int = 2500
    tokenizer: str = "Qwen/Qwen3-Embedding-0.6B"


class ChunkDraft(BaseModel):
    ordinal: int = Field(
        ge=0, description="Position within the document version, contiguous from 0"
    )
    parent_ordinal: int | None = Field(
        default=None, description="Ordinal of the parent-section chunk, if parent/child chunking"
    )
    is_parent: bool = False
    block_type: BlockType
    block_ids: list[str] = Field(default_factory=list, description="Canonical blocks covered")
    section_path: list[str] = Field(default_factory=list)
    content: str = Field(description="Display/generation text: the source body, not rewritten")
    embedding_text: str = Field(description="Title + section path + labels + body (plan §12.3)")
    content_hash: str = Field(pattern=SHA256_PATTERN, description="sha256 of `content`")
    token_count: int = Field(ge=0)
    location: SourceLocation = SourceLocation()
    identifiers: list[str] = Field(
        default_factory=list, description="Exact identifiers found, e.g. 'HR-142-B' (lexical boost)"
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Chunker(Protocol):
    @property
    def config(self) -> ChunkerConfig: ...

    def chunk(self, document: CanonicalDocument) -> list[ChunkDraft]: ...
