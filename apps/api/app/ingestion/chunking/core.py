"""Shared pure chunk construction, explicit source coverage and bounded structural units."""

import hashlib
import re
from bisect import bisect_right
from dataclasses import dataclass, field
from typing import Protocol

from app.ingestion.canonical import Block, BlockType, CanonicalDocument, SourceLocation
from app.ingestion.chunking.types import ChunkDraft, ChunkerConfig

STRUCTURAL = {BlockType.TABLE, BlockType.CODE}
_IDENTIFIER = re.compile(r"\b[A-Z]{2,}(?:-\d+)+(?:-[A-Z0-9]+)*\b")


class TextTokenizer(Protocol):
    @property
    def fingerprint(self) -> str: ...
    def count(self, text: str) -> int: ...
    def offsets(self, text: str) -> list[tuple[int, int]]: ...


@dataclass(frozen=True)
class Span:
    block: Block
    start: int
    end: int


@dataclass
class Unit:
    text: str
    spans: list[Span]
    kind: BlockType
    separate: bool = False
    warnings: list[str] = field(default_factory=list)


def validate_config(config: ChunkerConfig) -> None:
    if not 0 <= config.overlap_tokens < config.target_tokens:
        raise ValueError("overlap must be nonnegative and smaller than the target")
    if not 0 < config.min_tokens <= config.target_tokens <= config.parent_max_tokens:
        raise ValueError("invalid child token limits")
    if not 0 < config.parent_min_tokens <= config.parent_max_tokens:
        raise ValueError("invalid parent token limits")


def sections(document: CanonicalDocument) -> list[tuple[list[str], list[Block]]]:
    result: list[tuple[list[str], list[Block]]] = []
    pending: list[Block] = []
    current: list[Block] = []
    key: tuple[tuple[str, ...], int | None, str | None] | None = None
    path: list[str] = []
    for block in document.blocks:
        if block.type is BlockType.FURNITURE:
            continue
        if block.type is BlockType.HEADING:
            if current:
                result.append((path, current))
                current = []
                key = None
            pending.append(block)
            continue
        new_path = list(block.heading_path)
        if not new_path and pending:
            new_path = [*pending[-1].heading_path, pending[-1].text]
        new_key = (tuple(new_path), block.slide, block.sheet)
        if current and key != new_key:
            result.append((path, current))
            current = []
        if not current:
            path, key = new_path, new_key
            current = pending
            pending = []
        current.append(block)
    if current:
        result.append((path, current))
    if pending:
        # Source-only headings must not disappear; distinguish genuinely body-less input.
        result.append(([*pending[-1].heading_path, pending[-1].text], pending))
    return result


def prose_units(
    block: Block,
    tokenizer: TextTokenizer,
    budget: int,
    overlap: int,
    minimum: int,
    recursive: bool,
    following_budget: int | None = None,
) -> list[Unit]:
    result = []
    start = 0
    all_offsets = tokenizer.offsets(block.text)
    while start < len(block.text):
        active_budget = (following_budget or budget) if result else budget
        active_overlap = min(overlap, active_budget // 3)
        first = bisect_right(all_offsets, start, key=lambda pair: pair[1])
        remaining_tokens = len(all_offsets) - first
        if remaining_tokens <= active_budget:
            end = len(block.text)
        else:
            # Avoid a tiny final child where a balanced cut is possible.
            cut = min(
                active_budget,
                max(1, remaining_tokens - min(minimum, active_budget) + active_overlap),
            )
            end = max(start + 1, max(stop for _, stop in all_offsets[first : first + cut]))
            if recursive:
                for separator in ("\n\n", "\n", ". ", " "):
                    boundary = block.text.rfind(separator, start + (end - start) // 2, end)
                    if boundary >= 0:
                        end = boundary + len(separator)
                        break
        while end > start + 1 and tokenizer.count(block.text[start:end]) > active_budget:
            end -= 1
        text = block.text[start:end]
        warnings = ["unsplittable_character"] if tokenizer.count(text) > active_budget else []
        result.append(Unit(text, [Span(block, start, end)], block.type, True, warnings))
        if end == len(block.text):
            break
        next_start = end
        if active_overlap:
            tail = tokenizer.offsets(text)
            if tail:
                next_start = start + tail[max(0, len(tail) - active_overlap)][0]
                while (
                    next_start < end
                    and tokenizer.count(block.text[next_start:end]) > active_overlap
                ):
                    next_start += 1
        # A multi-token Unicode scalar cannot be split. Always advance by a full character.
        start = max(start + 1, next_start)
    return result


def structural_units(block: Block, tokenizer: TextTokenizer, budget: int) -> list[Unit]:
    if tokenizer.count(block.text) <= budget:
        return [Unit(block.text, [Span(block, 0, len(block.text))], block.type, True)]
    header = ""
    if block.type is BlockType.TABLE and block.table is not None:
        values = ([block.table.header] if block.table.header else []) + block.table.rows
        rendered = "\n".join(" | ".join(row) for row in values)
        if rendered != block.text or any("\n" in value for row in values for value in row):
            return [
                Unit(
                    block.text,
                    [Span(block, 0, len(block.text))],
                    block.type,
                    True,
                    ["unsplittable_table_layout"],
                )
            ]
        if block.table.header:
            header = " | ".join(block.table.header) + ("\n" if block.table.rows else "")
        if header and tokenizer.count(header) >= budget:
            return [
                Unit(
                    block.text,
                    [Span(block, 0, len(block.text))],
                    block.type,
                    True,
                    ["unsplittable_table_header"],
                )
            ]
    lines = block.text[len(header) :].splitlines(keepends=True)
    result: list[Unit] = []
    start = len(header)
    group_start = start
    body = ""

    def emit(end: int) -> None:
        if not body:
            return
        text = header + body
        spans = ([Span(block, 0, len(header))] if header else []) + [Span(block, group_start, end)]
        warnings = ["unsplittable_row_or_line"] if tokenizer.count(text) > budget else []
        result.append(Unit(text, spans, block.type, True, warnings))

    for line in lines:
        if body and tokenizer.count(header + body + line) > budget:
            emit(start)
            body, group_start = "", start
        body += line
        start += len(line)
    emit(start)
    if not result:
        result.append(
            Unit(
                block.text,
                [Span(block, 0, len(block.text))],
                block.type,
                True,
                ["unsplittable_table_header"],
            )
        )
    return result


def join_units(units: list[Unit]) -> Unit:
    return Unit(
        "\n\n".join(unit.text for unit in units),
        [span for unit in units for span in unit.spans],
        next(
            (unit.kind for unit in reversed(units) if unit.kind is not BlockType.HEADING),
            BlockType.HEADING,
        ),
        any(unit.separate for unit in units),
        list(dict.fromkeys(warning for unit in units for warning in unit.warnings)),
    )


def child_units(
    blocks: list[Block],
    tokenizer: TextTokenizer,
    config: ChunkerConfig,
    recursive: bool,
) -> list[Unit]:
    heads: list[Unit] = []
    result: list[Unit] = []
    current: list[Unit] = []
    for block in blocks:
        if block.type is BlockType.HEADING:
            heads.append(Unit(block.text, [Span(block, 0, len(block.text))], block.type))
            continue
        if heads and not block.text.strip():
            heads.append(Unit(block.text, [Span(block, 0, len(block.text))], block.type))
            continue
        reserve = tokenizer.count(join_units(heads).text) + 2 if heads else 0
        budget = config.target_tokens - reserve
        if budget <= 0:
            # An oversized heading is an explicit first-child exception; it must not force
            # every subsequent body fragment into a one-character chunk.
            budget = config.target_tokens
        if block.type in STRUCTURAL:
            units = structural_units(block, tokenizer, budget)
        elif tokenizer.count(block.text) > budget:
            units = prose_units(
                block,
                tokenizer,
                budget,
                config.overlap_tokens,
                config.min_tokens,
                recursive,
                following_budget=config.target_tokens,
            )
        else:
            units = [Unit(block.text, [Span(block, 0, len(block.text))], block.type)]
        if heads:
            units[0] = join_units([*heads, units[0]])
            if tokenizer.count(units[0].text) > config.target_tokens:
                units[0].warnings.append("unsplittable_heading_context")
            heads = []
        for unit in units:
            if current and (
                unit.separate
                or current[-1].separate
                or tokenizer.count(join_units([*current, unit]).text) > config.target_tokens
            ):
                result.append(join_units(current))
                current = []
            current.append(unit)
    if current:
        result.append(join_units(current))
    if len(result) > 1:
        previous, tail = result[-2:]
        # A small final prose paragraph can share a suffix of its predecessor, rather than
        # becoming a low-value child. Never rebalance a table, code line or overlapped fragment.
        if (
            not previous.separate
            and not tail.separate
            and tokenizer.count(tail.text) < config.min_tokens
        ):
            span = previous.spans[-1]
            text = span.block.text[span.start : span.end]
            offsets = tokenizer.offsets(text)
            needed = config.min_tokens - tokenizer.count(tail.text)
            if offsets:
                cut = offsets[max(0, len(offsets) - needed)][0]
                while (
                    cut > 0 and tokenizer.count(text[cut:] + "\n\n" + tail.text) < config.min_tokens
                ):
                    cut -= 1
                prefix, suffix = previous.text[: len(previous.text) - len(text) + cut], text[cut:]
                if (
                    cut > 0
                    and tokenizer.count(prefix) >= config.min_tokens
                    and tokenizer.count(suffix + "\n\n" + tail.text) <= config.target_tokens
                ):
                    previous.text = prefix
                    previous.spans[-1] = Span(span.block, span.start, span.start + cut)
                    tail.text = suffix + "\n\n" + tail.text
                    tail.spans.insert(0, Span(span.block, span.start + cut, span.end))
    if heads:
        unit = join_units(heads)
        unit.warnings.append("heading_without_body")
        if tokenizer.count(unit.text) > config.target_tokens:
            unit.warnings.append("unsplittable_heading_context")
        result.append(unit)
    return result


def parent_groups(
    units: list[Unit], tokenizer: TextTokenizer, config: ChunkerConfig
) -> list[list[Unit]]:
    groups: list[list[Unit]] = []
    current: list[Unit] = []
    for unit in units:
        if (
            current
            and tokenizer.count(join_units([*current, unit]).text) > config.parent_max_tokens
        ):
            groups.append(current)
            current = []
        current.append(unit)
    if current:
        groups.append(current)
    if len(groups) > 1:
        previous, tail = groups[-2:]
        while (
            len(previous) > 1 and tokenizer.count(join_units(tail).text) < config.parent_min_tokens
        ):
            if (
                tokenizer.count(join_units(previous[:-1]).text) < config.parent_min_tokens
                or tokenizer.count(join_units([previous[-1], *tail]).text)
                > config.parent_max_tokens
            ):
                break
            tail.insert(0, previous.pop())
    return groups


def draft(
    unit: Unit,
    document: CanonicalDocument,
    path: list[str],
    tokenizer: TextTokenizer,
    config: ChunkerConfig,
    ordinal: int,
    *,
    parent: int | None = None,
    is_parent: bool = False,
) -> ChunkDraft:
    blocks = list({span.block.block_id: span.block for span in unit.spans}.values())
    pages = [
        page
        for block in blocks
        for page in ([block.page] if block.page else []) + [box.page for box in block.bbox]
    ]
    slides = [block.slide for block in blocks if block.slide is not None]
    starts = [block.row_start for block in blocks if block.row_start is not None]
    ends = [block.row_end for block in blocks if block.row_end is not None]
    limit = config.parent_max_tokens if is_parent else config.target_tokens
    count = tokenizer.count(unit.text)
    labels = document.metadata.get("labels", [])
    label_text = (
        "\n".join(label for label in labels if isinstance(label, str))
        if isinstance(labels, list)
        else ""
    )
    return ChunkDraft(
        ordinal=ordinal,
        parent_ordinal=parent,
        is_parent=is_parent,
        block_type=BlockType.PARAGRAPH if is_parent else unit.kind,
        block_ids=[block.block_id for block in blocks],
        section_path=path,
        content=unit.text,
        embedding_text="\n".join(
            part for part in (document.title, " > ".join(path), label_text, unit.text) if part
        ),
        content_hash=hashlib.sha256(unit.text.encode("utf-8")).hexdigest(),
        token_count=count,
        location=SourceLocation(
            page_start=min(pages) if pages else None,
            page_end=max(pages) if pages else None,
            slide_start=min(slides) if slides else None,
            slide_end=max(slides) if slides else None,
            sheet=next((block.sheet for block in blocks if block.sheet), None),
            row_start=min(starts) if starts else None,
            row_end=max(ends) if ends else None,
        ),
        identifiers=list(dict.fromkeys(_IDENTIFIER.findall(unit.text))),
        metadata={
            "source_spans": [
                {"block_id": span.block.block_id, "start": span.start, "end": span.end}
                for span in unit.spans
            ],
            "bbox": [box.model_dump() for block in blocks for box in block.bbox],
            "chunker_config": config.model_dump(),
            "tokenizer_sha256": tokenizer.fingerprint,
            "warnings": unit.warnings,
            "unsplittable": count > limit,
            "below_minimum": count < (config.parent_min_tokens if is_parent else config.min_tokens),
        },
    )
