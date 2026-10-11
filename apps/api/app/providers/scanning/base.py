"""Contract: malware scanning (T1.0). Implementations: ClamAV + Noop (Codex, T2.3).

Scanners receive raw bytes (callers enforce size limits before scanning) and never raise for an
infected file: infection is a normal result. They raise only for operational failures, using
`ScannerUnavailableError` so callers can classify the failure as retryable.
"""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class ScanStatus(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    SKIPPED = "skipped"  # no scanner configured (NoopScanner); rejected when a scan is required


class ScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: ScanStatus
    scanner: str  # e.g. "clamav", "noop"
    signature: str | None = None  # malware name when INFECTED; never document content
    detail: str | None = None  # safe, human-readable note (no paths, no secrets)


class ScannerUnavailableError(RuntimeError):
    """The scanner couldn't be reached or timed out (retryable for the ingestion job)."""


@runtime_checkable
class MalwareScanner(Protocol):
    @property
    def name(self) -> str: ...

    async def scan(self, data: bytes, *, filename: str | None = None) -> ScanResult:
        """Scan `data`: INFECTED/CLEAN/SKIPPED; raises ScannerUnavailableError on failure."""
        ...
