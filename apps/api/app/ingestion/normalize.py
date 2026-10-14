"""Conservative canonical normalization. Never NFKC or indiscriminate body-text removal."""

import re
import unicodedata
from collections import defaultdict
from functools import lru_cache

from lingua import LanguageDetector, LanguageDetectorBuilder

from app.ingestion.canonical import Block, BlockType, CanonicalDocument
from app.ingestion.parsing.docling import block_id

NORMALIZATION_VERSION = 1
_CONTROLS = dict.fromkeys(
    map(
        ord,
        "\u061c\u200b\u200c\u200d\u200e\u200f\u2060\ufeff"
        "\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069",
    )
)


@lru_cache(maxsize=1)
def _detector() -> LanguageDetector:
    return (
        LanguageDetectorBuilder.from_all_languages()
        .with_low_accuracy_mode()
        .with_minimum_relative_distance(0.25)
        .build()
    )


def _language(text: str) -> str | None:
    if sum(character.isalpha() for character in text) < 20:
        return None
    detected = _detector().detect_language_of(text)
    return detected.iso_code_639_1.name.lower() if detected is not None else None


def _margin(block: Block, document: CanonicalDocument) -> bool:
    sizes = document.metadata.get("page_sizes", {})
    for box in block.bbox:
        height = sizes.get(str(box.page), {}).get("height")
        if box.y1 <= 40 or (isinstance(height, (int, float)) and box.y0 >= height - 40):
            return True
    return block.type is BlockType.FURNITURE


def _furniture_key(text: str) -> str:
    if re.fullmatch(r"(?:page\s*)?\d+(?:\s*(?:of|/)\s*\d+)?", text, flags=re.IGNORECASE):
        return re.sub(r"\d+", "#", text.lower())
    return text


def normalize_document(
    document: CanonicalDocument, *, retain_raw: bool = False
) -> CanonicalDocument:
    output = document.model_copy(deep=True)
    candidates: dict[str, set[int]] = defaultdict(set)
    for block in output.blocks:
        original = block.text
        controls = sum(ord(character) in _CONTROLS for character in original)
        if controls:
            block.extra["removed_invisible_controls"] = controls
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
        if block.type not in {BlockType.CODE, BlockType.TABLE, BlockType.FURNITURE}:
            block.language = _language(block.text)
        # Only explicitly detected furniture or top-margin boxes are candidates. Repeated
        # clauses in the body remain evidence, even when they occur on every page.
        if block.page and _margin(block, output):
            candidates[_furniture_key(block.text)].add(block.page)
    for block in output.blocks:
        if len(candidates.get(_furniture_key(block.text), set())) >= 2 and _margin(block, output):
            block.type = BlockType.FURNITURE
            block.language = None
    language = _language(
        " ".join(
            block.text
            for block in output.blocks
            if block.type not in {BlockType.CODE, BlockType.TABLE, BlockType.FURNITURE}
        )
    )
    output.languages = sorted(
        {block.language for block in output.blocks if block.language}
        | ({language} if language else set())
    )
    output.normalization_version = NORMALIZATION_VERSION
    return output


def normalize(document: CanonicalDocument) -> CanonicalDocument:
    """Stage entry point agreed with Claude; forensic text remains an explicit policy choice."""
    return normalize_document(document)
