"""Fail-closed validation for untrusted document uploads.

The validator deliberately has no database or storage dependencies.  Callers pass a binary
stream and, when needed, the SHA-256 fingerprints already present in the *same* knowledge base.
"""

from __future__ import annotations

import hashlib
import io
import re
import warnings
import zipfile
from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import filetype  # type: ignore[import-untyped]
from charset_normalizer import from_bytes
from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader
from pypdf.errors import PdfReadError


class ValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FLAGGED = "flagged"


class ValidationReason(StrEnum):
    EMPTY_FILE = "empty_file"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_EXTENSION = "unsupported_extension"
    BLOCKED_EXTENSION = "blocked_extension"
    UNKNOWN_FILE_TYPE = "unknown_file_type"
    MIME_MISMATCH = "mime_mismatch"
    INVALID_FORMAT = "invalid_format"
    EXECUTABLE_CONTENT = "executable_content"
    SCRIPT_CONTENT = "script_content"
    ARCHIVE_TOO_MANY_ENTRIES = "archive_too_many_entries"
    ARCHIVE_TOO_LARGE = "archive_too_large"
    ARCHIVE_COMPRESSION_RATIO = "archive_compression_ratio"
    ARCHIVE_NESTED = "archive_nested"
    ARCHIVE_PATH_TRAVERSAL = "archive_path_traversal"
    OFFICE_MACROS = "office_macros"
    PDF_ENCRYPTED = "pdf_encrypted"
    PDF_TOO_MANY_PAGES = "pdf_too_many_pages"
    PDF_ACTIVE_CONTENT = "pdf_active_content"
    IMAGE_DIMENSIONS_EXCEEDED = "image_dimensions_exceeded"
    IMAGE_TOO_MANY_PIXELS = "image_too_many_pixels"
    TIFF_TOO_MANY_PAGES = "tiff_too_many_pages"
    TEXT_DECODE_FAILED = "text_decode_failed"
    TEXT_BINARY_CONTENT = "text_binary_content"
    TEXT_TOO_MANY_LINES = "text_too_many_lines"
    DUPLICATE_IN_KB = "duplicate_in_kb"
    POLYGLOT_CONTENT = "polyglot_content"
    VALIDATION_ERROR = "validation_error"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    status: ValidationStatus
    reasons: tuple[ValidationReason, ...]
    detected_mime: str | None
    sha256: str


@dataclass(frozen=True, slots=True)
class ValidationConfig:
    max_file_bytes: int = 50 * 1024 * 1024
    max_archive_entries: int = 10_000
    max_archive_uncompressed_bytes: int = 250 * 1024 * 1024
    max_archive_entry_ratio: float = 100.0
    max_pdf_pages: int = 2_000
    max_image_width: int = 25_000
    max_image_height: int = 25_000
    max_image_pixels: int = 100_000_000
    max_tiff_pages: int = 500
    max_text_lines: int = 2_000_000


_EXPECTED_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
    ".html": "text/html",
    ".htm": "text/html",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
}
# Public allowlist (plan §5.3): the upload API rejects other extensions before presigning.
SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(_EXPECTED_MIME)
_BLOCKED_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".docm",
    ".exe",
    ".jar",
    ".js",
    ".jse",
    ".msi",
    ".ps1",
    ".pptm",
    ".py",
    ".sh",
    ".vbs",
    ".vbe",
    ".wsf",
    ".xlsm",
}
_ARCHIVE_EXTENSIONS = {
    ".7z",
    ".bz2",
    ".gz",
    ".jar",
    ".rar",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
}
_EXECUTABLE_MAGICS = (
    b"MZ",
    b"\x7fELF",
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
)
_PDF_ACTIVE_TOKEN = re.compile(rb"/(?:JS|JavaScript|OpenAction|Launch)\b", re.IGNORECASE)
_HTML_MARKER = re.compile(r"^(?:<!doctype\s+html|<html\b|<head\b|<body\b)", re.IGNORECASE)
_HTML_COMMENT = re.compile(r"^<!--.*?-->", re.DOTALL)
_HTML_TAG = re.compile(r"</?[A-Za-z][A-Za-z0-9:-]*(?:\s[^<>]*?)?/?>")
_OOXML_MIMES = {
    b"wordprocessingml.document.main+xml": _EXPECTED_MIME[".docx"],
    b"presentationml.presentation.main+xml": _EXPECTED_MIME[".pptx"],
    b"spreadsheetml.sheet.main+xml": _EXPECTED_MIME[".xlsx"],
}


def _read_and_hash(stream: BinaryIO, max_buffer_bytes: int) -> tuple[bytes, str, bool]:
    digest = hashlib.sha256()
    buffered = bytearray()
    too_large = False
    while chunk := stream.read(1024 * 1024):
        digest.update(chunk)
        if len(buffered) <= max_buffer_bytes:
            remaining = max_buffer_bytes + 1 - len(buffered)
            buffered.extend(chunk[:remaining])
        too_large = too_large or len(buffered) > max_buffer_bytes
    return bytes(buffered), digest.hexdigest(), too_large


def _has_executable_magic(data: bytes) -> bool:
    return any(data.startswith(magic) for magic in _EXECUTABLE_MAGICS)


def _decode_text(data: bytes) -> str | None:
    try:
        if data.startswith(b"\xef\xbb\xbf"):
            return data.decode("utf-8-sig")
        if data.startswith((b"\xff\xfe", b"\xfe\xff")):
            return data.decode("utf-16")
    except UnicodeDecodeError:
        return None
    match = from_bytes(data).best()
    return None if match is None else str(match)


def _has_binary_controls(data: bytes, text: str) -> bool:
    unicode_bom = (b"\xff\xfe", b"\xfe\xff", b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")
    raw_controls = sum(byte < 32 and byte not in b"\t\n\r\f" for byte in data)
    if not data.startswith(unicode_bom) and (
        b"\x00" in data or raw_controls > max(0, len(data) // 100)
    ):
        return True
    disallowed_controls = sum(
        ord(character) < 32 and character not in "\t\n\r\f" for character in text
    )
    return disallowed_controls > max(0, len(text) // 100)


def _looks_like_html(data: bytes, extension: str) -> bool:
    text = _decode_text(data)
    if text is None or _has_binary_controls(data, text):
        return False
    candidate = text.lstrip("\ufeff \t\n\r")
    while comment := _HTML_COMMENT.match(candidate):
        candidate = candidate[comment.end() :].lstrip()
    if _HTML_MARKER.match(candidate):
        return True
    return extension in {".htm", ".html"} and _HTML_TAG.search(candidate) is not None


def _safe_archive_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not (
        path.is_absolute()
        or ".." in path.parts
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized) is not None
    )


def _inspect_ooxml(
    data: bytes, config: ValidationConfig
) -> tuple[str | None, set[ValidationReason]]:
    reasons: set[ValidationReason] = set()
    detected_mime: str | None = None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > config.max_archive_entries:
                reasons.add(ValidationReason.ARCHIVE_TOO_MANY_ENTRIES)

            total_size = 0
            for entry in entries:
                total_size += entry.file_size
                if not _safe_archive_name(entry.filename):
                    reasons.add(ValidationReason.ARCHIVE_PATH_TRAVERSAL)
                suffix = Path(entry.filename).suffix.lower()
                if suffix in _ARCHIVE_EXTENSIONS:
                    reasons.add(ValidationReason.ARCHIVE_NESTED)
                if entry.filename.lower().endswith("vbaproject.bin"):
                    reasons.add(ValidationReason.OFFICE_MACROS)
                ratio = (
                    float("inf")
                    if entry.compress_size == 0 and entry.file_size > 0
                    else entry.file_size / max(entry.compress_size, 1)
                )
                if ratio > config.max_archive_entry_ratio:
                    reasons.add(ValidationReason.ARCHIVE_COMPRESSION_RATIO)

            if total_size > config.max_archive_uncompressed_bytes:
                reasons.add(ValidationReason.ARCHIVE_TOO_LARGE)

            try:
                content_types_entry = archive.getinfo("[Content_Types].xml")
            except KeyError:
                content_types = b""
            else:
                content_types_ratio = content_types_entry.file_size / max(
                    content_types_entry.compress_size, 1
                )
                if (
                    content_types_entry.file_size <= 1024 * 1024
                    and content_types_ratio <= config.max_archive_entry_ratio
                ):
                    content_types = archive.read(content_types_entry, pwd=None)
                else:
                    content_types = b""
            for marker, mime in _OOXML_MIMES.items():
                if marker in content_types:
                    detected_mime = mime
                    break
            if b"macroEnabled" in content_types or b"vbaProject" in content_types:
                reasons.add(ValidationReason.OFFICE_MACROS)

            # Only read tiny, reasonably compressed members to identify nested archives whose
            # names have no useful suffix. Never inflate suspicious members for inspection.
            if not reasons.intersection(
                {
                    ValidationReason.ARCHIVE_COMPRESSION_RATIO,
                    ValidationReason.ARCHIVE_TOO_LARGE,
                    ValidationReason.ARCHIVE_TOO_MANY_ENTRIES,
                }
            ):
                for entry in entries:
                    if entry.is_dir() or entry.file_size > 64 * 1024:
                        continue
                    with archive.open(entry) as member:
                        prefix = member.read(8)
                    if prefix.startswith(b"PK\x03\x04"):
                        reasons.add(ValidationReason.ARCHIVE_NESTED)
                        break
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, zipfile.LargeZipFile):
        reasons.add(ValidationReason.INVALID_FORMAT)
    return detected_mime, reasons


def _detect_mime(
    data: bytes, extension: str, config: ValidationConfig
) -> tuple[str | None, set[ValidationReason]]:
    if data.startswith(b"PK\x03\x04") or data.startswith(b"PK\x05\x06"):
        return _inspect_ooxml(data, config)
    if data.startswith(b"%PDF-"):
        return "application/pdf", set()
    if _looks_like_html(data, extension):
        return "text/html", set()

    kind = filetype.guess(data[:8192])
    if kind is not None:
        return kind.mime, set()

    if extension in {".csv", ".md", ".markdown", ".txt"}:
        if _decode_text(data) is not None:
            return _EXPECTED_MIME[extension], set()
        return None, {ValidationReason.TEXT_DECODE_FAILED}
    return None, set()


def _validate_pdf(data: bytes, config: ValidationConfig) -> set[ValidationReason]:
    reasons: set[ValidationReason] = set()
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            reasons.add(ValidationReason.PDF_ENCRYPTED)
            return reasons
        if len(reader.pages) > config.max_pdf_pages:
            reasons.add(ValidationReason.PDF_TOO_MANY_PAGES)
    except (OSError, ValueError, PdfReadError):
        reasons.add(ValidationReason.INVALID_FORMAT)
    if _PDF_ACTIVE_TOKEN.search(data):
        reasons.add(ValidationReason.PDF_ACTIVE_CONTENT)
    end_marker = data.rfind(b"%%EOF")
    if end_marker >= 0 and data[end_marker + len(b"%%EOF") :].strip(b"\x00\t\n\r "):
        reasons.add(ValidationReason.POLYGLOT_CONTENT)
    return reasons


def _validate_image(data: bytes, extension: str, config: ValidationConfig) -> set[ValidationReason]:
    reasons: set[ValidationReason] = set()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
                if width > config.max_image_width or height > config.max_image_height:
                    reasons.add(ValidationReason.IMAGE_DIMENSIONS_EXCEEDED)
                if width * height > config.max_image_pixels:
                    reasons.add(ValidationReason.IMAGE_TOO_MANY_PIXELS)
                if (
                    extension in {".tif", ".tiff"}
                    and getattr(image, "n_frames", 1) > config.max_tiff_pages
                ):
                    reasons.add(ValidationReason.TIFF_TOO_MANY_PAGES)
                image.verify()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        reasons.add(ValidationReason.IMAGE_TOO_MANY_PIXELS)
    except (OSError, UnidentifiedImageError, ValueError):
        reasons.add(ValidationReason.INVALID_FORMAT)
    return reasons


def _validate_text(data: bytes, config: ValidationConfig) -> set[ValidationReason]:
    reasons: set[ValidationReason] = set()
    text = _decode_text(data)
    if text is None:
        reasons.add(ValidationReason.TEXT_DECODE_FAILED)
        return reasons
    if _has_binary_controls(data, text):
        reasons.add(ValidationReason.TEXT_BINARY_CONTENT)
    if text.count("\n") + (1 if text else 0) > config.max_text_lines:
        reasons.add(ValidationReason.TEXT_TOO_MANY_LINES)
    return reasons


_FLAG_REASONS = {ValidationReason.DUPLICATE_IN_KB, ValidationReason.PDF_ACTIVE_CONTENT}


def validate_file(
    stream: BinaryIO,
    filename: str,
    *,
    config: ValidationConfig | None = None,
    existing_sha256s_in_kb: Collection[str] = (),
) -> ValidationResult:
    """Validate an upload without raising for malformed content.

    ``existing_sha256s_in_kb`` must be scoped by the caller to the current tenant and knowledge
    base.  Keeping that lookup outside this module prevents accidental cross-tenant side channels.
    """

    policy = config or ValidationConfig()
    sha256 = hashlib.sha256(b"").hexdigest()
    detected_mime: str | None = None
    reasons: set[ValidationReason] = set()
    try:
        data, sha256, too_large = _read_and_hash(stream, policy.max_file_bytes)
        extension = Path(filename).suffix.lower()

        if not data:
            reasons.add(ValidationReason.EMPTY_FILE)
        if too_large:
            reasons.add(ValidationReason.FILE_TOO_LARGE)
        if extension in _BLOCKED_EXTENSIONS:
            reasons.add(ValidationReason.BLOCKED_EXTENSION)
        elif extension not in _EXPECTED_MIME:
            reasons.add(ValidationReason.UNSUPPORTED_EXTENSION)

        if _has_executable_magic(data):
            reasons.add(ValidationReason.EXECUTABLE_CONTENT)
        if data.startswith(b"#!"):
            reasons.add(ValidationReason.SCRIPT_CONTENT)

        detected_mime, inspection_reasons = _detect_mime(data, extension, policy)
        reasons.update(inspection_reasons)
        expected_mime = _EXPECTED_MIME.get(extension)
        if detected_mime is None:
            reasons.add(ValidationReason.UNKNOWN_FILE_TYPE)
        elif expected_mime is not None and detected_mime != expected_mime:
            reasons.add(ValidationReason.MIME_MISMATCH)

        if detected_mime == "application/pdf":
            reasons.update(_validate_pdf(data, policy))
        elif detected_mime is not None and detected_mime.startswith("image/"):
            reasons.update(_validate_image(data, extension, policy))
        elif detected_mime is not None and detected_mime.startswith("text/"):
            reasons.update(_validate_text(data, policy))

        if sha256 in existing_sha256s_in_kb:
            reasons.add(ValidationReason.DUPLICATE_IN_KB)
    except Exception:  # Untrusted stream implementations must fail closed, never escape.
        reasons.add(ValidationReason.VALIDATION_ERROR)

    ordered_reasons = tuple(sorted(reasons, key=str))
    if not ordered_reasons:
        status = ValidationStatus.ACCEPTED
    elif set(ordered_reasons).issubset(_FLAG_REASONS):
        status = ValidationStatus.FLAGGED
    else:
        status = ValidationStatus.REJECTED
    return ValidationResult(status, ordered_reasons, detected_mime, sha256)
