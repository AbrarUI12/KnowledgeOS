from __future__ import annotations

import hashlib
import io
import zipfile
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from PIL import Image
from pypdf import PdfReader, PdfWriter

from app.security.file_validation import (
    ValidationConfig,
    ValidationReason,
    ValidationResult,
    ValidationStatus,
    validate_file,
)

FIXTURES = Path(__file__).parent / "fixtures" / "files"


def _validate_bytes(
    content: bytes,
    filename: str,
    *,
    config: ValidationConfig | None = None,
    duplicates: set[str] | None = None,
) -> ValidationResult:
    return validate_file(
        io.BytesIO(content),
        filename,
        config=config,
        existing_sha256s_in_kb=duplicates or set(),
    )


def _zip_bytes(members: dict[str, bytes], *, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return output.getvalue()


def _document_content_types(*, macro: bool = False) -> bytes:
    kind = "macroEnabled" if macro else "document"
    return (
        '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/'
        '2006/content-types"><Override PartName="/word/document.xml" ContentType="application/'
        f'vnd.ms-word.{kind}.main+xml"/></Types>'
    ).encode()


@pytest.mark.unit
@pytest.mark.parametrize(
    "filename",
    [
        "valid.pdf",
        "valid.docx",
        "valid.pptx",
        "valid.xlsx",
        "valid.csv",
        "valid.html",
        "valid.md",
        "valid.txt",
        "valid.png",
        "valid.jpg",
        "valid.tiff",
    ],
)
def test_accepts_each_supported_fixture(filename: str) -> None:
    with (FIXTURES / filename).open("rb") as stream:
        result = validate_file(stream, filename)

    assert result.status is ValidationStatus.ACCEPTED
    assert result.reasons == ()
    assert result.sha256 == hashlib.sha256((FIXTURES / filename).read_bytes()).hexdigest()


@pytest.mark.unit
def test_rejects_executable_renamed_as_pdf() -> None:
    result = _validate_bytes(b"MZ" + bytes(100), "quarterly-report.pdf")

    assert result.status is ValidationStatus.REJECTED
    assert ValidationReason.EXECUTABLE_CONTENT in result.reasons
    assert ValidationReason.MIME_MISMATCH in result.reasons


@pytest.mark.unit
@pytest.mark.parametrize("filename", ["payload.exe", "payload.js", "payload.ps1", "macro.docm"])
def test_rejects_blocked_extensions(filename: str) -> None:
    result = _validate_bytes(b"plain text", filename)

    assert ValidationReason.BLOCKED_EXTENSION in result.reasons


@pytest.mark.unit
def test_rejects_shebang_script_renamed_as_text() -> None:
    result = _validate_bytes(b"#!/bin/sh\necho unsafe\n", "notes.txt")

    assert ValidationReason.SCRIPT_CONTENT in result.reasons


@pytest.mark.unit
def test_rejects_archive_entry_count_limit() -> None:
    content = _zip_bytes(
        {
            "[Content_Types].xml": _document_content_types(),
            "word/a.xml": b"a",
            "word/b.xml": b"b",
        }
    )
    result = _validate_bytes(
        content, "document.docx", config=ValidationConfig(max_archive_entries=2)
    )

    assert ValidationReason.ARCHIVE_TOO_MANY_ENTRIES in result.reasons


@pytest.mark.unit
def test_rejects_archive_total_uncompressed_limit() -> None:
    content = _zip_bytes(
        {"[Content_Types].xml": _document_content_types(), "word/document.xml": b"x" * 256}
    )
    result = _validate_bytes(
        content,
        "document.docx",
        config=ValidationConfig(
            max_archive_uncompressed_bytes=100,
            max_archive_entry_ratio=10_000,
        ),
    )

    assert ValidationReason.ARCHIVE_TOO_LARGE in result.reasons


@pytest.mark.unit
def test_rejects_zip_bomb_ratio_generated_in_memory() -> None:
    content = _zip_bytes(
        {"[Content_Types].xml": _document_content_types(), "word/document.xml": bytes(100_000)}
    )
    result = _validate_bytes(
        content,
        "document.docx",
        config=ValidationConfig(max_archive_entry_ratio=10),
    )

    assert ValidationReason.ARCHIVE_COMPRESSION_RATIO in result.reasons


@pytest.mark.unit
@pytest.mark.parametrize("member", ["../escape.xml", "/absolute.xml", "C:\\escape.xml"])
def test_rejects_archive_path_traversal(member: str) -> None:
    content = _zip_bytes({"[Content_Types].xml": _document_content_types(), member: b"unsafe"})

    result = _validate_bytes(content, "document.docx")

    assert ValidationReason.ARCHIVE_PATH_TRAVERSAL in result.reasons


@pytest.mark.unit
def test_rejects_nested_archive_even_without_archive_suffix() -> None:
    nested = _zip_bytes({"payload": b"unsafe"})
    content = _zip_bytes(
        {"[Content_Types].xml": _document_content_types(), "word/media/blob": nested}
    )

    result = _validate_bytes(content, "document.docx")

    assert ValidationReason.ARCHIVE_NESTED in result.reasons


@pytest.mark.unit
def test_rejects_office_macros_generated_in_memory() -> None:
    content = _zip_bytes(
        {
            "[Content_Types].xml": _document_content_types(macro=True),
            "word/vbaProject.bin": b"macro",
        }
    )

    result = _validate_bytes(content, "document.docm")

    assert ValidationReason.BLOCKED_EXTENSION in result.reasons
    assert ValidationReason.OFFICE_MACROS in result.reasons


@pytest.mark.unit
def test_rejects_encrypted_pdf_generated_in_memory() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt("runtime-only-password")
    output = io.BytesIO()
    writer.write(output)

    result = _validate_bytes(output.getvalue(), "encrypted.pdf")

    assert ValidationReason.PDF_ENCRYPTED in result.reasons


@pytest.mark.unit
def test_rejects_pdf_over_page_limit() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.add_blank_page(width=72, height=72)
    output = io.BytesIO()
    writer.write(output)

    result = _validate_bytes(
        output.getvalue(), "long.pdf", config=ValidationConfig(max_pdf_pages=1)
    )

    assert ValidationReason.PDF_TOO_MANY_PAGES in result.reasons


@pytest.mark.unit
def test_flags_pdf_active_content() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    with pytest.warns(DeprecationWarning, match="add_js is deprecated"):
        writer.add_js("app.alert('unsafe')")
    output = io.BytesIO()
    writer.write(output)

    result = _validate_bytes(output.getvalue(), "active.pdf")

    assert result.status is ValidationStatus.FLAGGED
    assert result.reasons == (ValidationReason.PDF_ACTIVE_CONTENT,)


@pytest.mark.unit
def test_rejects_pdf_polyglot_generated_in_memory() -> None:
    content = (FIXTURES / "valid.pdf").read_bytes() + b"MZ-runtime-polyglot"

    result = _validate_bytes(content, "polyglot.pdf")

    assert ValidationReason.POLYGLOT_CONTENT in result.reasons


@pytest.mark.unit
def test_rejects_image_dimension_and_pixel_limits() -> None:
    output = io.BytesIO()
    Image.new("RGB", (4, 3), "white").save(output, format="PNG")

    result = _validate_bytes(
        output.getvalue(),
        "large.png",
        config=ValidationConfig(max_image_width=3, max_image_pixels=10),
    )

    assert ValidationReason.IMAGE_DIMENSIONS_EXCEEDED in result.reasons
    assert ValidationReason.IMAGE_TOO_MANY_PIXELS in result.reasons


@pytest.mark.unit
def test_rejects_tiff_page_limit() -> None:
    first = Image.new("RGB", (2, 2), "white")
    second = Image.new("RGB", (2, 2), "black")
    output = io.BytesIO()
    first.save(output, format="TIFF", save_all=True, append_images=[second])

    result = _validate_bytes(
        output.getvalue(), "multipage.tiff", config=ValidationConfig(max_tiff_pages=1)
    )

    assert ValidationReason.TIFF_TOO_MANY_PAGES in result.reasons


@pytest.mark.unit
def test_rejects_text_line_limit() -> None:
    result = _validate_bytes(
        b"one\ntwo\nthree\n", "many.txt", config=ValidationConfig(max_text_lines=2)
    )

    assert ValidationReason.TEXT_TOO_MANY_LINES in result.reasons


@pytest.mark.unit
def test_rejects_binary_control_bytes_renamed_as_text() -> None:
    result = _validate_bytes(b"\x00\x01\x02\x03", "payload.txt")

    assert ValidationReason.TEXT_BINARY_CONTENT in result.reasons


@pytest.mark.unit
def test_accepts_bom_marked_utf16_text() -> None:
    result = _validate_bytes("KnowledgeOS".encode("utf-16"), "unicode.txt")

    assert result.status is ValidationStatus.ACCEPTED


@pytest.mark.unit
@pytest.mark.parametrize(
    ("content", "filename"),
    [
        (b"\xef\xbb\xbf<html><body>UTF-8 BOM</body></html>", "bom.html"),
        ("<html><body>UTF-16 BOM</body></html>".encode("utf-16"), "bom.html"),
        (b"<!-- exported page --><html><body>Comment</body></html>", "comment.html"),
        (b"<div>HTML fragment</div>", "fragment.html"),
    ],
)
def test_accepts_html_exports_and_fragments(content: bytes, filename: str) -> None:
    result = _validate_bytes(content, filename)

    assert result.status is ValidationStatus.ACCEPTED
    assert result.detected_mime == "text/html"


@pytest.mark.unit
def test_rejects_file_size_limit_but_hashes_entire_stream() -> None:
    content = b"0123456789"
    result = _validate_bytes(content, "large.txt", config=ValidationConfig(max_file_bytes=5))

    assert ValidationReason.FILE_TOO_LARGE in result.reasons
    assert result.sha256 == hashlib.sha256(content).hexdigest()


@pytest.mark.unit
def test_duplicate_check_uses_only_caller_supplied_kb_hashes() -> None:
    content = b"known document"
    digest = hashlib.sha256(content).hexdigest()

    unique = _validate_bytes(content, "known.txt")
    duplicate = _validate_bytes(content, "known.txt", duplicates={digest})

    assert ValidationReason.DUPLICATE_IN_KB not in unique.reasons
    assert ValidationReason.DUPLICATE_IN_KB in duplicate.reasons
    assert duplicate.status is ValidationStatus.FLAGGED


@pytest.mark.unit
@settings(max_examples=150, deadline=None)
@given(content=st.binary(max_size=4096), filename=st.text(max_size=80))
def test_random_bytes_never_raise(content: bytes, filename: str) -> None:
    result = _validate_bytes(content, filename)

    assert isinstance(result.status, ValidationStatus)
    assert len(result.sha256) == 64


class _BrokenStream:
    def read(self, _size: int) -> bytes:
        raise OSError("untrusted stream failure")


@pytest.mark.unit
def test_broken_stream_fails_closed_without_raising() -> None:
    result = validate_file(_BrokenStream(), "file.pdf")  # type: ignore[arg-type]

    assert result.status is ValidationStatus.REJECTED
    assert result.reasons == (ValidationReason.VALIDATION_ERROR,)


@pytest.mark.unit
def test_committed_pdf_fixture_is_readable_by_parser() -> None:
    reader = PdfReader(FIXTURES / "valid.pdf")
    assert len(reader.pages) == 1
