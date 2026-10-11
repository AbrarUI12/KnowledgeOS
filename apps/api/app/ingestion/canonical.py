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
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

CANONICAL_SCHEMA_VERSION = 1
SHA256_PATTERN = r"^[0-9a-f]{64}$"


class SourceLocation(BaseModel):
    """Where a piece of evidence lives in its source, for citations and source navigation.

    All numbers are 1-based and inclusive. PDFs/DOCX use pages, PPTX uses slides, XLSX/CSV use a
    sheet plus a row range. Ranges allow a chunk to span several pages/slides/rows.
    """

    model_config = ConfigDict(frozen=True)

    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    slide_start: int | None = Field(default=None, ge=1)
    slide_end: int | None = Field(default=None, ge=1)
    sheet: str | None = None
    row_start: int | None = Field(default=None, ge=1)
    row_end: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _ranges_are_ordered(self) -> Self:
        for start, end in (
            (self.page_start, self.page_end),
            (self.slide_start, self.slide_end),
            (self.row_start, self.row_end),
        ):
            if start is not None and end is not None and end < start:
                raise ValueError("location range end must be >= start")
        return self


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

    @model_validator(mode="after")
    def _blocks_are_ordered_and_unique(self) -> Self:
        seen: set[str] = set()
        previous = -1
        for block in self.blocks:
            if block.source_order <= previous:
                raise ValueError("block source_order must be strictly increasing")
            if block.block_id in seen:
                raise ValueError(f"duplicate block_id {block.block_id!r}")
            previous = block.source_order
            seen.add(block.block_id)
        return self
