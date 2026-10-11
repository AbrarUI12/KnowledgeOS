"""Contract: document parsers (T1.0). Implementations: Codex T3.2 (Docling), T3.3
(Office/tabular/OCR).

Parsers are synchronous, CPU-bound and DB-free. The ingestion PARSING stage (Claude, T3.5) runs them
in a subprocess with time and memory limits, so implementations must not rely on global state.
"""

from typing import Protocol, runtime_checkable

from app.ingestion.canonical import CanonicalDocument


class ParserError(Exception):
    """The file could not be parsed. `retryable` is False for corrupt/unsupported input."""

    def __init__(self, message: str, *, code: str, retryable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@runtime_checkable
class DocumentParser(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def supports(self, mime_type: str) -> bool: ...

    def parse(self, data: bytes, *, filename: str, mime_type: str) -> CanonicalDocument:
        """Parse validated, malware-scanned bytes into the canonical artifact."""
        ...
