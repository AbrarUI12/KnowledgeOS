import hashlib
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from tokenizers import Tokenizer, models, pre_tokenizers  # type: ignore[import-untyped]

from app.ingestion.canonical import Block, BlockType, CanonicalDocument, TableData
from app.ingestion.chunking.recursive_fixed import RecursiveFixedChunker
from app.ingestion.chunking.structure_aware import StructureAwareChunker
from app.ingestion.chunking.tokenizer import ModelTokenizer
from app.ingestion.chunking.types import Chunker, ChunkerConfig

pytestmark = pytest.mark.unit


@pytest.fixture(scope="session")
def tokenizer(tmp_path_factory: pytest.TempPathFactory) -> ModelTokenizer:
    # Real byte-level BPE, no mocked splitting/counting. The real Qwen asset is tested below.
    alphabet = sorted(pre_tokenizers.ByteLevel.alphabet())
    backend = Tokenizer(models.BPE(vocab={char: n for n, char in enumerate(alphabet)}, merges=[]))
    backend.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False)
    path = tmp_path_factory.mktemp("chunk-tokenizer") / "tokenizer.json"
    backend.save(str(path))
    return ModelTokenizer("fixture-byte-bpe", tokenizer_file=path)


def document(blocks: list[Block]) -> CanonicalDocument:
    return CanonicalDocument(
        title="Handbook",
        mime_type="text/plain",
        parser_name="fixture",
        parser_version="1",
        blocks=blocks,
        metadata={"labels": ["HR"]},
    )


def block(order: int, text: str, kind: BlockType = BlockType.PARAGRAPH, **kwargs: object) -> Block:
    return Block.model_validate(
        dict(block_id=f"block{order:04d}", source_order=order, text=text, type=kind, **kwargs)
    )


def config(**kwargs: object) -> ChunkerConfig:
    return ChunkerConfig.model_validate(
        dict(
            target_tokens=80,
            overlap_tokens=12,
            min_tokens=15,
            parent_min_tokens=160,
            parent_max_tokens=240,
            tokenizer="fixture-byte-bpe",
            **kwargs,
        )
    )


@pytest.mark.parametrize("chunker_type", [StructureAwareChunker, RecursiveFixedChunker])
def test_headings_sections_provenance_and_identifiers(
    tokenizer: ModelTokenizer, chunker_type: type[StructureAwareChunker]
) -> None:
    source = document(
        [
            block(0, "Eligibility", BlockType.HEADING),
            block(
                1,
                "HR-142-B: active employees get sixteen weeks.",
                heading_path=["Eligibility"],
                page=1,
            ),
            block(2, "Margin", BlockType.FURNITURE, page=2),
            block(3, "Manager approval is required.", heading_path=["Eligibility"], page=2),
            block(4, "Engineering", BlockType.HEADING),
            block(5, "Runbook details.", heading_path=["Engineering"], slide=3),
        ]
    )
    original = source.model_copy(deep=True)
    chunker = chunker_type(config(name=chunker_type.name), tokenizer=tokenizer)
    assert isinstance(chunker, Chunker)
    chunks = chunker.chunk(source)
    children = [c for c in chunks if not c.is_parent]
    assert "Eligibility\n\nHR-142-B" in children[0].content
    assert children[0].identifiers == ["HR-142-B"]
    assert children[0].embedding_text.startswith("Handbook\nEligibility\nHR\n")
    assert children[-1].location.slide_start == 3
    assert not any("block0002" in c.block_ids for c in chunks)
    assert all(c.section_path in [["Eligibility"], ["Engineering"]] for c in chunks)
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    assert all(c.content_hash == hashlib.sha256(c.content.encode()).hexdigest() for c in chunks)
    if chunker_type is StructureAwareChunker:
        assert all(
            c.parent_ordinal is not None and chunks[c.parent_ordinal].is_parent for c in children
        )
    else:
        assert not any(c.is_parent or c.parent_ordinal is not None for c in chunks)
    assert source == original
    assert chunker.chunk(source) == chunks


def test_table_rows_repeat_headers_and_code_splits_only_lines(tokenizer: ModelTokenizer) -> None:
    rows = [[str(n), "Employee category " + str(n)] for n in range(12)]
    header = ["Number", "Name"]
    table_text = "\n".join(" | ".join(row) for row in [header, *rows])
    source = document(
        [
            block(
                0,
                table_text,
                BlockType.TABLE,
                table=TableData(header=header, rows=rows),
                sheet="Staff",
                row_start=2,
                row_end=13,
            ),
            block(
                1, "\n".join(f"print('line {n}')" for n in range(15)), BlockType.CODE, sheet="Staff"
            ),
        ]
    )
    children = [
        c
        for c in StructureAwareChunker(config(), tokenizer=tokenizer).chunk(source)
        if not c.is_parent
    ]
    tables = [c for c in children if c.block_type is BlockType.TABLE]
    assert len(tables) > 1
    assert all(c.content.startswith("Number | Name\n") for c in tables)
    assert all(
        c.location.sheet == "Staff" and c.location.row_start == 2 and c.location.row_end == 13
        for c in tables
    )
    assert all(row[1] in "\n".join(c.content for c in tables) for row in rows)
    codes = [c for c in children if c.block_type is BlockType.CODE]
    assert all(
        line.startswith("print(") and line.endswith(")")
        for c in codes
        for line in c.content.splitlines()
    )
    assert all(c.token_count <= 80 for c in children)


def test_oversized_units_and_bodyless_heading_are_explicit(tokenizer: ModelTokenizer) -> None:
    source = document(
        [block(0, "x" * 300, BlockType.CODE), block(1, "Only a heading", BlockType.HEADING)]
    )
    children = [
        c
        for c in StructureAwareChunker(config(), tokenizer=tokenizer).chunk(source)
        if not c.is_parent
    ]
    assert children[0].metadata["unsplittable"]
    assert "unsplittable_row_or_line" in children[0].metadata["warnings"]
    assert "heading_without_body" in children[-1].metadata["warnings"]


def test_small_final_paragraph_is_balanced_without_overlap(tokenizer: ModelTokenizer) -> None:
    source = document([block(0, "a" * 75), block(1, "b" * 8)])
    chunks = StructureAwareChunker(config(), tokenizer=tokenizer).chunk(source)
    children = [c for c in chunks if not c.is_parent]
    assert len(children) == 2
    assert all(15 <= c.token_count <= 80 for c in children)
    first, second = children
    assert first.metadata["source_spans"][-1]["end"] == second.metadata["source_spans"][0]["start"]
    assert first.content + second.content.split("\n\n")[0] == "a" * 75


def test_parent_groups_are_bounded_and_rebalanced_when_possible(tokenizer: ModelTokenizer) -> None:
    source = document([block(n, str(n) * 70) for n in range(5)])
    chunks = StructureAwareChunker(config(), tokenizer=tokenizer).chunk(source)
    parents = [c for c in chunks if c.is_parent]
    assert len(parents) == 2
    assert all(140 <= c.token_count <= 240 for c in parents)
    assert [s["block_id"] for c in parents for s in c.metadata["source_spans"]] == [
        b.block_id for b in source.blocks
    ]


@given(
    texts=st.lists(
        st.text(alphabet=st.characters(exclude_categories=["Cs"]), min_size=1, max_size=150),
        min_size=1,
        max_size=8,
    ),
    chunker_type=st.sampled_from([StructureAwareChunker, RecursiveFixedChunker]),
)
@settings(max_examples=70, deadline=None)
def test_source_coverage_order_overlap_caps_and_determinism(
    texts: list[str], chunker_type: type[StructureAwareChunker], tokenizer: ModelTokenizer
) -> None:
    source = document([block(n, text) for n, text in enumerate(texts)])
    chunker = chunker_type(config(name=chunker_type.name), tokenizer=tokenizer)
    chunks = chunker.chunk(source)
    assert chunker.chunk(source) == chunks
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))
    children = [c for c in chunks if not c.is_parent]
    for c in chunks:
        assert c.token_count == tokenizer.count(c.content)
        assert c.token_count <= (240 if c.is_parent else 80) or c.metadata["unsplittable"]
    for b in source.blocks:
        spans = [
            s for c in children for s in c.metadata["source_spans"] if s["block_id"] == b.block_id
        ]
        covered: set[int] = set()
        last_end = 0
        for span in spans:
            start, end = span["start"], span["end"]
            assert 0 <= start <= end <= len(b.text)
            assert start <= last_end
            if start < last_end:
                assert tokenizer.count(b.text[start:last_end]) <= 12
            covered.update(range(start, end))
            last_end = end
        assert covered == set(range(len(b.text)))
    orders = [
        next(b.source_order for b in source.blocks if b.block_id == s["block_id"])
        for c in children
        for s in c.metadata["source_spans"]
    ]
    assert orders == sorted(orders)


@pytest.mark.slow
def test_real_qwen_tokenizer_unicode_and_chunk_budget() -> None:
    tokenizer = ModelTokenizer("Qwen/Qwen3-Embedding-0.6B")
    text = "Café policy: বাংলা 中文 🧑‍💻 HR-142-B. " * 100
    source = document([block(0, text)])
    chunks = StructureAwareChunker(tokenizer=tokenizer).chunk(source)
    children = [c for c in chunks if not c.is_parent]
    assert len(children) > 1
    assert all(c.token_count <= 600 for c in children)
    assert all("\ufffd" not in c.content for c in children)
    assert tokenizer.count(text) > 600
    covered = {
        i
        for c in children
        for span in c.metadata["source_spans"]
        for i in range(span["start"], span["end"])
    }
    assert covered == set(range(len(text)))


@given(values=st.lists(st.text(alphabet="abcdef ", max_size=50), min_size=1, max_size=20))
@settings(max_examples=40, deadline=None)
def test_table_row_order_coverage_and_header_invariants(
    values: list[str], tokenizer: ModelTokenizer
) -> None:
    rows = [[str(n), value] for n, value in enumerate(values)]
    header = ["ID", "Data"]
    text = "\n".join(" | ".join(row) for row in [header, *rows])
    source = document([block(0, text, BlockType.TABLE, table=TableData(header=header, rows=rows))])
    children = [
        c
        for c in StructureAwareChunker(config(), tokenizer=tokenizer).chunk(source)
        if not c.is_parent
    ]
    assert all(c.content.splitlines()[0] == "ID | Data" for c in children)
    assert [line for c in children for line in c.content.splitlines()[1:]] == [
        " | ".join(row) for row in rows
    ]
    assert all(c.token_count <= 80 or c.metadata["unsplittable"] for c in children)


def test_heading_with_empty_body_has_explicit_orphan_warning(tokenizer: ModelTokenizer) -> None:
    source = document([block(0, "Only heading", BlockType.HEADING), block(1, "")])
    children = [
        c
        for c in StructureAwareChunker(config(), tokenizer=tokenizer).chunk(source)
        if not c.is_parent
    ]
    assert len(children) == 1
    assert "heading_without_body" in children[0].metadata["warnings"]


@given(
    pairs=st.lists(
        st.tuples(
            st.text(alphabet="abc", min_size=1, max_size=40),
            st.text(alphabet="xyz ", min_size=1, max_size=150),
        ),
        min_size=1,
        max_size=5,
    )
)
@settings(max_examples=40, deadline=None)
def test_headings_are_never_separated_from_available_body(
    pairs: list[tuple[str, str]], tokenizer: ModelTokenizer
) -> None:
    blocks = []
    for n, (heading, body) in enumerate(pairs):
        blocks.extend(
            [
                block(2 * n, heading, BlockType.HEADING),
                block(2 * n + 1, body, heading_path=[heading]),
            ]
        )
    children = [
        c
        for c in StructureAwareChunker(config(), tokenizer=tokenizer).chunk(document(blocks))
        if not c.is_parent
    ]
    for n, (_, body) in enumerate(pairs):
        child = next(c for c in children if f"block{2 * n:04d}" in c.block_ids)
        assert f"block{2 * n + 1:04d}" in child.block_ids
        assert child.metadata["source_spans"][-1]["end"] > 0
        assert "heading_without_body" not in child.metadata["warnings"] or not body.strip()


def test_unsplittable_multiline_table_cell_keeps_original_text(tokenizer: ModelTokenizer) -> None:
    rows = [["A", "long cell\n" + "text " * 40]]
    text = "Name | Notes\nA | " + rows[0][1]
    source = document(
        [block(0, text, BlockType.TABLE, table=TableData(header=["Name", "Notes"], rows=rows))]
    )
    children = [
        c
        for c in StructureAwareChunker(config(), tokenizer=tokenizer).chunk(source)
        if not c.is_parent
    ]
    assert len(children) == 1
    assert children[0].content == text
    assert children[0].metadata["unsplittable"]
    assert "unsplittable_table_layout" in children[0].metadata["warnings"]


@pytest.mark.parametrize("heading_size", [70, 100])
def test_large_heading_does_not_fragment_entire_body_into_tiny_chunks(
    heading_size: int, tokenizer: ModelTokenizer
) -> None:
    heading = "H" * heading_size
    source = document(
        [block(0, heading, BlockType.HEADING), block(1, "b" * 500, heading_path=[heading])]
    )
    children = [
        c
        for c in StructureAwareChunker(config(), tokenizer=tokenizer).chunk(source)
        if not c.is_parent
    ]
    assert len(children) <= 10
    assert all(c.token_count <= 80 for c in children[1:])
    assert children[0].metadata["unsplittable"] == (heading_size == 100)


def test_oversized_header_is_not_amplified_for_every_row(tokenizer: ModelTokenizer) -> None:
    header = ["H" * 100]
    rows = [[str(n)] for n in range(30)]
    text = "\n".join(" | ".join(row) for row in [header, *rows])
    source = document([block(0, text, BlockType.TABLE, table=TableData(header=header, rows=rows))])
    children = [
        c
        for c in StructureAwareChunker(config(), tokenizer=tokenizer).chunk(source)
        if not c.is_parent
    ]
    assert len(children) == 1
    assert children[0].content == text
    assert "unsplittable_table_header" in children[0].metadata["warnings"]


def test_invalid_configuration_and_missing_model_do_not_fallback(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="overlap"):
        StructureAwareChunker(ChunkerConfig(overlap_tokens=600))
    with pytest.raises(Exception, match=r"No such file|cannot find|os error"):
        ModelTokenizer("missing", tokenizer_file=tmp_path / "missing.json").count("policy")
    with pytest.raises(ValueError, match="tokenizer model"):
        StructureAwareChunker(tokenizer=ModelTokenizer("other-model"))


def test_independently_loaded_tokenizers_produce_identical_provenance(
    tokenizer: ModelTokenizer,
) -> None:
    other = ModelTokenizer(tokenizer.model, tokenizer_file=tokenizer.tokenizer_file)
    assert tokenizer.fingerprint == other.fingerprint
    source = document([block(0, "Unicode café policy: 16 weeks.")])
    assert StructureAwareChunker(config(), tokenizer=tokenizer).chunk(
        source
    ) == StructureAwareChunker(config(), tokenizer=other).chunk(source)
