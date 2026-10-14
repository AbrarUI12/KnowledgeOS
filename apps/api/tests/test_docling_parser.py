from io import BytesIO
from pathlib import Path

import pytest
from docx import Document

from app.ingestion.canonical import BlockType
from app.ingestion.parsing.base import ParserError
from app.ingestion.parsing.docling import DoclingParser
from app.ingestion.parsing.isolation import run_isolated

pytestmark = pytest.mark.unit
CORPUS = Path(__file__).resolve().parents[3] / "evals" / "fixtures" / "corpus" / "demo"


@pytest.mark.parametrize(
    ("filename", "mime_type"),
    [
        ("acme_hr_handbook_2026.pdf", "application/pdf"),
        (
            "acme_eng_runbook.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
        ("acme_support_troubleshooting.html", "text/html"),
        ("acme_eng_architecture.md", "text/markdown"),
    ],
)
def test_real_format_canonical_snapshot(filename: str, mime_type: str, snapshot: object) -> None:
    assets = Path(__file__).resolve().parents[1] / ".venv" / "docling-assets"
    document = DoclingParser(artifacts_path=assets if assets.exists() else None).parse(
        (CORPUS / filename).read_bytes(), filename=filename, mime_type=mime_type
    )
    assert document.blocks
    assert [b.source_order for b in document.blocks] == list(range(len(document.blocks)))
    assert document.model_dump(mode="json") == snapshot
    if mime_type == "application/pdf":
        assert document.page_count
        assert all(block.page for block in document.blocks)
        assert any(block.bbox for block in document.blocks)
    if filename.endswith(".md"):
        assert any(block.type is BlockType.HEADING for block in document.blocks)


def test_real_child_timeout() -> None:
    with pytest.raises(ParserError) as error:
        run_isolated("tests.parser_probe", ["hang"], timeout_seconds=0.2, memory_bytes=1024**3)
    assert error.value.code == "parser_timeout"
    assert error.value.retryable


def test_docx_hierarchy_lists_and_structured_table() -> None:
    source = Document()
    source.add_heading("Policy", level=1)
    source.add_heading("Eligibility", level=2)
    source.add_paragraph("Active employees", style="List Bullet")
    table = source.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Category"
    table.cell(0, 1).text = "Weeks"
    table.cell(1, 0).text = "Employee"
    table.cell(1, 1).text = "16"
    output = BytesIO()
    source.save(output)
    document = DoclingParser().parse(
        output.getvalue(),
        filename="policy.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    listing = next(block for block in document.blocks if block.type is BlockType.LIST)
    assert listing.heading_path == ["Policy", "Eligibility"]
    parsed_table = next(block for block in document.blocks if block.type is BlockType.TABLE)
    assert parsed_table.table is not None
    assert ["Employee", "16"] in parsed_table.table.rows
    again = DoclingParser().parse(
        output.getvalue(),
        filename="policy.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert document == again


def test_real_child_memory_limit() -> None:
    with pytest.raises(ParserError) as error:
        run_isolated(
            "tests.parser_probe", ["allocate"], timeout_seconds=5, memory_bytes=32 * 1024**2
        )
    assert error.value.code == "parser_memory_limit"


def test_unsupported_and_empty_inputs_fail_before_launch() -> None:
    parser = DoclingParser()
    with pytest.raises(ParserError, match="Unsupported"):
        parser.parse(b"content", filename="input.exe", mime_type="application/octet-stream")
    with pytest.raises(ParserError, match="empty"):
        parser.parse(b"", filename="empty.pdf", mime_type="application/pdf")
