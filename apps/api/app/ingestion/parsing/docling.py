"""Docling-to-canonical adapter; no DB, network URLs or caller-supplied filesystem paths."""

import hashlib
import json
import tempfile
import unicodedata
from importlib.metadata import version
from pathlib import Path

from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.items.table.table import TableItem
from docling_core.types.doc.items.text import SectionHeaderItem, TextItem

from app.ingestion.canonical import Block, BlockType, BoundingBox, CanonicalDocument, TableData
from app.ingestion.parsing.base import ParserError
from app.ingestion.parsing.isolation import run_isolated

FORMATS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/html": ".html",
    "text/markdown": ".md",
}


def block_id(order: int, text: str) -> str:
    normalized = unicodedata.normalize("NFC", text)
    return hashlib.sha256(f"{order}\n{normalized}".encode()).hexdigest()


def to_canonical(document: DoclingDocument, *, filename: str, mime_type: str) -> CanonicalDocument:
    blocks: list[Block] = []
    headings: list[str] = []
    labels = {
        "title": BlockType.HEADING,
        "section_header": BlockType.HEADING,
        "list_item": BlockType.LIST,
        "code": BlockType.CODE,
        "caption": BlockType.CAPTION,
        "page_header": BlockType.FURNITURE,
        "page_footer": BlockType.FURNITURE,
    }
    for item, _ in document.iterate_items():
        if not isinstance(item, (TextItem, TableItem)):
            continue
        kind = labels.get(item.label.value, BlockType.PARAGRAPH)
        table = None
        heading_level = None
        if isinstance(item, TableItem):
            kind = BlockType.TABLE
            grid = item.data.grid
            values = [[cell.text for cell in row] for row in grid]
            has_header = bool(grid and any(cell.column_header for cell in grid[0]))
            table = TableData(
                header=values[0] if has_header else [], rows=values[1:] if has_header else values
            )
            text = "\n".join(" | ".join(row) for row in values)
        else:
            text = item.text
            if kind is BlockType.HEADING:
                heading_level = min(
                    9, max(1, item.level if isinstance(item, SectionHeaderItem) else 1)
                )
                headings = headings[: heading_level - 1]
        order = len(blocks)
        boxes = []
        for provenance in item.prov:
            page = document.pages.get(provenance.page_no)
            box = provenance.bbox
            if page is not None:
                box = box.to_top_left_origin(page.size.height)
            boxes.append(
                BoundingBox(page=provenance.page_no, x0=box.l, y0=box.t, x1=box.r, y1=box.b)
            )
        blocks.append(
            Block(
                block_id=block_id(order, text),
                type=kind,
                text=text,
                table=table,
                heading_level=heading_level,
                heading_path=list(headings),
                source_order=order,
                page=item.prov[0].page_no if item.prov else None,
                bbox=boxes,
            )
        )
        if kind is BlockType.HEADING:
            headings.append(text)
    return CanonicalDocument(
        title=next(
            (block.text for block in blocks if block.type is BlockType.HEADING), Path(filename).stem
        ),
        mime_type=mime_type,
        page_count=len(document.pages) or None,
        blocks=blocks,
        parser_name="docling",
        parser_version=version("docling"),
    )


class DoclingParser:
    name = "docling"

    def __init__(
        self,
        *,
        timeout_seconds: float = 120,
        memory_bytes: int = 4 * 1024**3,
        artifacts_path: Path | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.memory_bytes = memory_bytes
        self.artifacts_path = artifacts_path

    @property
    def version(self) -> str:
        return version("docling")

    def supports(self, mime_type: str) -> bool:
        return mime_type in FORMATS

    def parse(self, data: bytes, *, filename: str, mime_type: str) -> CanonicalDocument:
        if not self.supports(mime_type):
            raise ParserError("Unsupported document format.", code="unsupported_format")
        if not data or len(data) > 50 * 1024**2:
            raise ParserError("Document is empty or too large.", code="parser_input_limit")
        with tempfile.TemporaryDirectory(prefix="kos-parser-") as temporary:
            directory = Path(temporary)
            source = directory / f"input{FORMATS[mime_type]}"
            output = directory / "canonical.json"
            source.write_bytes(data)
            request = directory / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "source": str(source),
                        "output": str(output),
                        "filename": filename,
                        "mime_type": mime_type,
                        "memory_bytes": self.memory_bytes,
                        "artifacts_path": str(self.artifacts_path.resolve())
                        if self.artifacts_path
                        else None,
                    }
                ),
                encoding="utf-8",
            )
            run_isolated(
                "app.ingestion.parsing.docling_worker",
                [str(request)],
                timeout_seconds=self.timeout_seconds,
                memory_bytes=self.memory_bytes,
                offline=self.artifacts_path is not None,
            )
            if not output.exists() or output.stat().st_size > 64 * 1024**2:
                raise ParserError(
                    "Parser output is missing or too large.", code="parser_output_limit"
                )
            return CanonicalDocument.model_validate_json(output.read_bytes())
