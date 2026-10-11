"""Contract: file-safety validation (T1.0). Implemented in app/security/file_validation.py (T2.3).

The validator is a pure function over bytes: no I/O, no database, never raises on hostile input.
It returns a `ValidationResult`; the ingestion VALIDATING stage (Claude, T3.5) maps REJECTED to
FAILED_PERMANENT and FLAGGED to the content-review policy. Reason codes are stable API values
(documented in docs/api/errors.md when surfaced to users).
"""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class ValidationStatus(StrEnum):
    ACCEPTED = "accepted"
    FLAGGED = "flagged"  # allowed, but needs attention (e.g. PDF with JavaScript actions)
    REJECTED = "rejected"


class ValidationLimits(BaseModel):
    """Per-deployment limits; defaults are conservative and configurable."""

    model_config = ConfigDict(frozen=True)

    max_bytes: int = 100 * 1024 * 1024
    max_pdf_pages: int = 2_000
    max_image_pixels: int = 80_000_000
    max_archive_entries: int = 10_000
    max_uncompressed_bytes: int = 1024 * 1024 * 1024
    max_compression_ratio: float = 100.0
    max_text_lines: int = 2_000_000


class ValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ValidationStatus
    reasons: tuple[str, ...] = Field(
        default=(), description="Stable reason codes, e.g. 'mime_mismatch', 'zip_bomb', 'macro'"
    )
    detected_mime: str | None = None
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


@runtime_checkable
class FileValidator(Protocol):
    def validate(
        self,
        data: bytes,
        *,
        filename: str,
        declared_mime: str | None = None,
        limits: ValidationLimits | None = None,
    ) -> ValidationResult:
        """Validate untrusted file bytes. Must never raise on malformed input."""
        ...
