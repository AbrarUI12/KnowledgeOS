from pathlib import Path

import pytest

from app.ingestion.canonical import Block, BlockType, BoundingBox, CanonicalDocument
from app.ingestion.normalize import normalize_document
from app.ingestion.parsing.base import ParserError
from app.ingestion.parsing.office import PPTX, XLSX, OfficeParser

pytestmark = pytest.mark.unit
CORPUS = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "corpus" / "demo"


@pytest.mark.parametrize(
    ("filename", "mime"),
    [
        ("acme_eng_architecture_slides.pptx", PPTX),
        ("acme_eng_team_metrics.xlsx", XLSX),
        ("acme_eng_metrics.csv", "text/csv"),
    ],
)
def test_real_office_snapshot(filename: str, mime: str, snapshot: object) -> None:
    result = OfficeParser(row_group_size=2).parse(
        (CORPUS / filename).read_bytes(), filename=filename, mime_type=mime
    )
    assert result.blocks
    assert result.model_dump(mode="json") == snapshot
    assert (
        OfficeParser(row_group_size=2).parse(
            (CORPUS / filename).read_bytes(), filename=filename, mime_type=mime
        )
        == result
    )


def test_semicolon_csv_row_ranges_and_caps() -> None:
    result = OfficeParser(row_group_size=1).parse(
        b"Name;Weeks\nAlice;16\nBob;12", filename="leave.csv", mime_type="text/csv"
    )
    assert result.blocks[0].row_start == 2
    assert result.blocks[1].row_end == 3
    assert result.blocks[0].table is not None
    assert result.blocks[0].table.header == ["Name", "Weeks"]
    with pytest.raises(ParserError) as error:
        OfficeParser(max_columns=1).parse(b"a,b\n1,2", filename="wide.csv", mime_type="text/csv")
    assert error.value.code == "parser_table_limit"


def test_normalization_preserves_code_and_original_input() -> None:
    document = CanonicalDocument(
        title="test",
        mime_type="text/plain",
        parser_name="fixture",
        parser_version="1",
        blocks=[
            Block(
                block_id="original1",
                source_order=0,
                type=BlockType.PARAGRAPH,
                text="  cafe\u0301\u202e\u200b   policy  ",
            ),
            Block(
                block_id="original2",
                source_order=1,
                type=BlockType.CODE,
                text="if x:\n    return x",
            ),
        ],
    )
    normalized = normalize_document(document, retain_raw=True)
    assert normalized.blocks[0].text == "café policy"
    assert normalized.blocks[0].raw_text == document.blocks[0].text
    assert normalized.blocks[1].text == "if x:\n    return x"
    assert document.normalization_version is None
    assert normalize_document(normalized, retain_raw=True) == normalized


def test_repeated_top_margin_is_furniture_not_body_clauses() -> None:
    blocks = [
        Block(
            block_id=f"header00{page}",
            source_order=page - 1,
            page=page,
            type=BlockType.PARAGRAPH,
            text="Acme Handbook",
            bbox=[BoundingBox(page=page, x0=10, y0=10, x1=100, y1=20)],
        )
        for page in (1, 2)
    ]
    blocks.append(
        Block(
            block_id="body0001",
            source_order=2,
            page=2,
            type=BlockType.PARAGRAPH,
            text="Acme Handbook",
            bbox=[BoundingBox(page=2, x0=10, y0=100, x1=100, y1=110)],
        )
    )
    document = CanonicalDocument(
        title="test",
        mime_type="application/pdf",
        parser_name="fixture",
        parser_version="1",
        blocks=blocks,
    )
    result = normalize_document(document)
    assert all(block.type is BlockType.FURNITURE for block in result.blocks[:2])
    assert result.blocks[2].type is BlockType.PARAGRAPH
