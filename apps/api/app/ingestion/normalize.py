"""Conservative canonical normalization. Never NFKC or indiscriminate body-text removal."""

import re
import unicodedata
from collections import defaultdict

from app.ingestion.canonical import BlockType, CanonicalDocument
from app.ingestion.parsing.docling import block_id

NORMALIZATION_VERSION = 1
_CONTROLS = dict.fromkeys(
    map(ord, "\u200b\u200c\u200d\u2060\ufeff\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")
)


def normalize_document(
    document: CanonicalDocument, *, retain_raw: bool = False
) -> CanonicalDocument:
    output = document.model_copy(deep=True)
    candidates: dict[str, set[int]] = defaultdict(set)
    for block in output.blocks:
        original = block.text
        block.text = unicodedata.normalize("NFC", original).translate(_CONTROLS)
        if block.type not in {BlockType.CODE, BlockType.TABLE}:
            block.text = re.sub(r"\s+", " ", block.text).strip()
        if retain_raw and original != block.text:
            block.raw_text = original
        if block.table:
            block.table.header = [
                unicodedata.normalize("NFC", text).translate(_CONTROLS)
                for text in block.table.header
            ]
            block.table.rows = [
                [unicodedata.normalize("NFC", text).translate(_CONTROLS) for text in row]
                for row in block.table.rows
            ]
        block.heading_path = [
            unicodedata.normalize("NFC", text).translate(_CONTROLS) for text in block.heading_path
        ]
        block.block_id = block_id(block.source_order, block.text)
        # Only explicitly detected furniture or top-margin boxes are candidates. Repeated
        # clauses in the body remain evidence, even when they occur on every page.
        if block.page and (
            block.type is BlockType.FURNITURE or any(box.y0 < 40 for box in block.bbox)
        ):
            candidates[block.text].add(block.page)
    for block in output.blocks:
        if len(candidates.get(block.text, set())) >= 2 and (
            block.type is BlockType.FURNITURE or any(box.y0 < 40 for box in block.bbox)
        ):
            block.type = BlockType.FURNITURE
    output.normalization_version = NORMALIZATION_VERSION
    return output
