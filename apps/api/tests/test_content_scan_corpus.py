"""Real parser/normalizer/scanner calibration regression, not a sanitized text fixture."""

import json
from pathlib import Path

import pytest

from app.ingestion.normalize import normalize
from app.ingestion.parsing.base import DocumentParser
from app.ingestion.parsing.docling import DoclingParser
from app.ingestion.parsing.office import OfficeParser
from app.security.content_scanner import RuleContentScanner
from app.security.content_types import ContentScanOutcome

CORPUS = Path(__file__).resolve().parents[3] / "evals/fixtures/corpus/demo"
FORMATS = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "html": "text/html",
    "markdown": "text/markdown",
    "txt": "text/plain",
}


@pytest.mark.slow
@pytest.mark.security
def test_only_poisoned_demo_document_is_flagged() -> None:
    parsers: list[DocumentParser] = [
        OfficeParser(),
        DoclingParser(artifacts_path=Path(__file__).resolve().parents[1] / ".venv/docling-assets"),
    ]
    scanner = RuleContentScanner()
    manifest = json.loads((CORPUS / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest) == 16
    for entry in manifest:
        mime = FORMATS[entry["format"]]
        parser = next(parser for parser in parsers if parser.supports(mime))
        path = CORPUS / entry["file"]
        canonical = parser.parse(path.read_bytes(), filename=path.name, mime_type=mime)
        result = scanner.scan(normalize(canonical))
        expected = (
            ContentScanOutcome.FLAGGED
            if path.name == "acme_eng_notes.txt"
            else ContentScanOutcome.CLEAN
        )
        assert result.outcome is expected, (path.name, result.model_dump())
