"""Contract: the canonical document artifact (plan §10.1, T1.0).

Every parser (Docling, Office, tabular, OCR; Codex T3.2/T3.3) produces a `CanonicalDocument`. It is
persisted as JSON in object storage so chunking and indexing can be reproduced without re-parsing
(plan §5.3). Chunkers consume it; the reader/inspect UI renders it.

Rules:
- `blocks` are in reading order; `source_order` is strictly increasing.
- `block_id` is a stable hash of (source_order, normalized text), so re-parsing identical
  input yields identical IDs.
- `page` / `slide` / `sheet` / `row_*` are 1-based when present.
- `furniture` blocks (repeated headers/footers) stay in the artifact but are never chunked.
"""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

CANONICAL_SCHEMA_VERSION = 1


class BlockType(StrEnum):
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    TABLE = "table"
    CODE = "code"
    CAPTION = "caption"
    IMAGE_TEXT = "image_text"  # OCR text from an image or scanned page
    FURNITURE = "furniture"  # repeated header/footer/page number


class BoundingBox(BaseModel):
    """Position on a page in PDF points, origin top-left."""

    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=1)
    x0: float
    y0: float
    x1: float
    y1: float


class TableData(BaseModel):
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class Block(BaseModel):
    block_id: str = Field(min_length=8, max_length=64)
    type: BlockType
    text: str = ""
    table: TableData | None = None
    heading_level: int | None = Field(default=None, ge=1, le=9)
    heading_path: list[str] = Field(
        default_factory=list, description="Ancestor headings, outermost first"
    )
    source_order: int = Field(ge=0)
    page: int | None = Field(default=None, ge=1)
    bbox: list[BoundingBox] = Field(default_factory=list)
    slide: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    row_start: int | None = Field(default=None, ge=1)
    row_end: int | None = Field(default=None, ge=1)
    language: str | None = None  # ISO 639-1 when detected
    ocr_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    raw_text: str | None = Field(
        default=None, description="Pre-normalization text, kept only when forensic policy requires"
    )
    extra: dict[str, Any] = Field(default_factory=dict)


class CanonicalDocument(BaseModel):
    schema_version: int = CANONICAL_SCHEMA_VERSION
    title: str
    languages: list[str] = Field(default_factory=list)
    mime_type: str
    page_count: int | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
    blocks: list[Block] = Field(default_factory=list)
    parser_name: str
    parser_version: str
    normalization_version: int | None = None
    warnings: list[str] = Field(default_factory=list, description="Safe diagnostics for the UI")
