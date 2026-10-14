import json
from difflib import get_close_matches
from io import BytesIO
from pathlib import Path

import pytest
import reportlab
from docling.backend.image_backend import ImageDocumentBackend
from docling.datamodel.base_models import InputFormat, Page
from docling.datamodel.document import ConversionResult, InputDocument
from docling_core.types.doc.base import BoundingBox as DoclingBox
from docling_core.types.doc.base import CoordOrigin, Size
from docling_core.types.doc.page import BoundingRectangle, TextCell
from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Table, TableStyle
from structlog.testing import capture_logs

from app.ingestion.canonical import Block, BlockType, BoundingBox, CanonicalDocument
from app.ingestion.normalize import normalize, normalize_document
from app.ingestion.parsing.base import ParserError
from app.ingestion.parsing.docling import DoclingParser
from app.ingestion.parsing.html import clean_html
from app.ingestion.parsing.isolation import run_isolated
from app.ingestion.parsing.ocr import OcrParser, add_ocr_provenance

pytestmark = pytest.mark.unit
ASSETS = Path(__file__).resolve().parents[1] / ".venv" / "docling-assets"


def image_fixture() -> bytes:
    image = Image.new("RGB", (1000, 400), "white")
    font = ImageFont.truetype(str(Path(reportlab.__file__).parent / "fonts" / "Vera.ttf"), 32)
    ImageDraw.Draw(image).multiline_text(
        (60, 60),
        "Acme employee policy\nPaid parental leave is sixteen weeks.",
        fill="black",
        font=font,
        spacing=30,
    )
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.mark.parametrize("mime", ["image/png", "application/pdf"])
def test_real_ocr_snapshot(mime: str, snapshot: object) -> None:
    data = image_fixture()
    if mime == "application/pdf":
        output = BytesIO()
        canvas = Canvas(output, pagesize=(1000, 400), invariant=True)
        canvas.drawImage(ImageReader(BytesIO(data)), 0, 0, width=1000, height=400)
        canvas.save()
        data = output.getvalue()
    document = OcrParser(artifacts_path=ASSETS).parse(data, filename="scan", mime_type=mime)
    words = " ".join(block.text for block in document.blocks).lower().split()
    for expected in ("acme", "parental", "leave", "sixteen", "weeks"):
        assert get_close_matches(expected, words, n=1, cutoff=0.8), (expected, words)
    assert document.page_count == 1
    assert all(block.page == 1 and block.bbox for block in document.blocks)
    assert any(block.ocr_confidence is not None for block in document.blocks)
    assert all(
        0 <= block.ocr_confidence <= 1
        for block in document.blocks
        if block.ocr_confidence is not None
    )
    # CPU-dependent confidence/bbox numerics are checked above; snapshot semantic structure.
    assert {
        "title": document.title,
        "page_count": document.page_count,
        "blocks": [
            {
                "text": b.text,
                "type": b.type.value,
                "page": b.page,
                "source_order": b.source_order,
                "ocr": b.ocr_confidence is not None,
                "heading_path": b.heading_path,
            }
            for b in document.blocks
        ],
    } == snapshot


def test_child_secrets_are_not_inherited(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    forbidden = {"DATABASE_URL", "S3_SECRET_ACCESS_KEY", "REDIS_URL", "HF_TOKEN"}
    for name in forbidden:
        monkeypatch.setenv(name, "synthetic-sensitive-value")
    output = tmp_path / "environment.json"
    run_isolated(
        "tests.parser_probe",
        ["environment", str(output)],
        timeout_seconds=5,
        memory_bytes=1024**3,
        offline=True,
    )
    environment = json.loads(output.read_text())
    assert not forbidden & environment.keys()
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["OMP_NUM_THREADS"] == "2"


def test_noisy_child_diagnostics_are_capped() -> None:
    with capture_logs() as logs, pytest.raises(ParserError) as error:
        run_isolated("tests.parser_probe", ["noisy"], timeout_seconds=5, memory_bytes=1024**3)
    assert error.value.code == "parser_failed"
    assert "END-OF-DIAGNOSTIC" not in str(error.value)
    logged = logs[-1]["stderr_tail"]
    assert "END-OF-DIAGNOSTIC" in logged
    assert len(logged) <= 2048


def test_html_cleanup_keeps_evidence() -> None:
    cleaned, metadata = clean_html(b"""<html><head><title>Policy</title>
      <link rel="canonical" href="https://example.test/policy"></head><body>
      <nav>Account menu</nav><div id="cookie-banner">Accept cookies</div>
      <h1>Eligibility</h1><p>Policy evidence</p><pre>if x:\n    return x</pre>
      <table><tr><td>16 weeks</td></tr></table><footer>Legal menu</footer></body></html>""")
    assert metadata == {"html_title": "Policy", "canonical_url": "https://example.test/policy"}
    assert all(word not in cleaned for word in (b"Account menu", b"Accept cookies", b"Legal menu"))
    assert b"Policy evidence" in cleaned
    assert b"    return x" in cleaned
    assert b"16 weeks" in cleaned
    _, malicious = clean_html(b'<link rel="canonical" href="javascript:evil()">')
    assert "canonical_url" not in malicious


def make_document(texts: list[str]) -> CanonicalDocument:
    return CanonicalDocument(
        title="policy",
        mime_type="text/plain",
        parser_name="fixture",
        parser_version="1",
        blocks=[
            Block(
                block_id=f"block000{index}", type=BlockType.PARAGRAPH, source_order=index, text=text
            )
            for index, text in enumerate(texts)
        ],
    )


def test_english_and_spanish_language_detection() -> None:
    english = normalize(
        make_document(
            [
                "All employees are eligible for sixteen weeks of paid parental leave. "
                "Please submit your request to human resources at least thirty days in advance."
            ]
        )
    )
    spanish = normalize(
        make_document(
            [
                "Todos los empleados tienen derecho a dieciséis semanas "
                "de permiso parental remunerado. "
                "Por favor envíe su solicitud al departamento de recursos humanos "
                "con treinta días de antelación."
            ]
        )
    )
    assert english.languages == ["en"]
    assert english.blocks[0].language == "en"
    assert spanish.languages == ["es"]
    assert spanish.blocks[0].language == "es"


def test_footer_page_numbers_are_furniture_not_body() -> None:
    document = make_document(["Page 1 of 2", "Page 2 of 2", "Page 2 of 2"])
    document.metadata["page_sizes"] = {"1": {"height": 800}, "2": {"height": 800}}
    for index, block in enumerate(document.blocks):
        block.page = min(index + 1, 2)
        y = 780 if index < 2 else 200
        block.bbox = [BoundingBox(page=block.page, x0=10, y0=y, x1=200, y1=y + 10)]
    result = normalize(document)
    assert [b.type for b in result.blocks] == [
        BlockType.FURNITURE,
        BlockType.FURNITURE,
        BlockType.PARAGRAPH,
    ]


def test_controls_preserve_forensics_and_do_not_apply_nfkc() -> None:
    document = make_document(["\u061c\u200e\u200f\u202e\u2066\u200b\uff21  café"])
    result = normalize_document(document, retain_raw=True)
    assert result.blocks[0].text == "\uff21 café"
    assert result.blocks[0].extra["removed_invisible_controls"] == 6
    assert result.blocks[0].raw_text == document.blocks[0].text
    assert normalize_document(result, retain_raw=True) == result


def test_input_limits_are_configurable() -> None:
    assert DoclingParser().supports("image/png")
    assert not DoclingParser(ocr=False).supports("image/png")
    with pytest.raises(ParserError) as error:
        DoclingParser(max_input_bytes=2).parse(b"long", filename="a.md", mime_type="text/markdown")
    assert error.value.code == "parser_input_limit"
    with pytest.raises(ValueError, match="limits must be positive"):
        OcrParser(max_pages=0)


def test_ocr_page_limit_is_enforced() -> None:
    output = BytesIO()
    canvas = Canvas(output, invariant=True)
    for _ in range(2):
        canvas.drawString(30, 100, "A page of employee policy evidence.")
        canvas.showPage()
    canvas.save()
    with pytest.raises(ParserError) as error:
        OcrParser(artifacts_path=ASSETS, max_pages=1).parse(
            output.getvalue(), filename="two-pages.pdf", mime_type="application/pdf"
        )
    assert error.value.code == "parser_failed"


def test_native_pdf_preserves_structured_table() -> None:
    output = BytesIO()
    canvas = Canvas(output, invariant=True)
    canvas.setFont("Helvetica-Bold", 20)
    canvas.drawString(60, 720, "Parental Leave Policy")
    table = Table(
        [["Category", "Weeks"], ["Employee", "16"], ["Manager", "12"]],
        colWidths=[180, 100],
        rowHeights=[30, 30, 30],
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 1, "black"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    table.wrapOn(canvas, 400, 400)
    table.drawOn(canvas, 60, 550)
    canvas.save()
    document = DoclingParser(artifacts_path=ASSETS).parse(
        output.getvalue(), filename="table.pdf", mime_type="application/pdf"
    )
    parsed = next(block for block in document.blocks if block.type is BlockType.TABLE)
    assert parsed.table is not None
    # PDF glyph extraction includes cell-edge padding; preserve it in the artifact, but compare
    # semantic cell values here without that layout-only padding (internal whitespace is kept).
    assert [cell.strip() for cell in parsed.table.header] == ["Category", "Weeks"]
    assert [[cell.strip() for cell in row] for row in parsed.table.rows] == [
        ["Employee", "16"],
        ["Manager", "12"],
    ]
    assert parsed.page == 1
    assert parsed.bbox


@pytest.mark.parametrize("from_ocr", [True, False])
def test_low_confidence_diagnostics_only_apply_to_ocr_cells(from_ocr: bool) -> None:
    document = make_document(["Policy evidence"])
    document.blocks[0].page = 1
    document.blocks[0].bbox = [BoundingBox(page=1, x0=10, y0=10, x1=90, y1=30)]
    cell = TextCell(
        index=0,
        text="Policy evidence",
        orig="Policy evidence",
        confidence=0.6,
        from_ocr=from_ocr,
        rect=BoundingRectangle.from_bounding_box(
            DoclingBox(l=10, t=10, r=90, b=30, coord_origin=CoordOrigin.TOPLEFT)
        ),
    )
    data = image_fixture()
    source = InputDocument(
        path_or_stream=BytesIO(data),
        format=InputFormat.IMAGE,
        backend=ImageDocumentBackend,
        filename="fixture.png",
    )
    backend = ImageDocumentBackend(source, BytesIO(data))
    parsed = backend.load_page(0).get_segmented_page()
    parsed.textline_cells = [cell]
    page = Page(page_no=1, size=Size(width=1000, height=400), parsed_page=parsed)
    add_ocr_provenance(document, ConversionResult(input=source, pages=[page]))
    backend.unload()  # type: ignore[no-untyped-call]  # upstream cleanup lacks annotations
    source._backend.unload()  # type: ignore[no-untyped-call]
    if from_ocr:
        assert document.blocks[0].ocr_confidence == 0.6
        assert document.warnings == ["low_ocr_confidence"]
        assert document.blocks[0].type is BlockType.IMAGE_TEXT
    else:
        assert document.blocks[0].ocr_confidence is None
        assert document.warnings == []
