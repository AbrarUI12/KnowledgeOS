"""Contract: content-security scanning of canonical text (plan §11, T1.0). Implementation: Codex
T3.4.

Defense in depth only: a CLEAN result never makes retrieved text trusted (generation still treats
all evidence as untrusted). Findings reference block IDs and rule IDs, never copy document text.
"""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from app.ingestion.canonical import CanonicalDocument


class ContentScanOutcome(StrEnum):
    CLEAN = "clean"
    FLAGGED = "flagged"  # searchable only if policy permits; marked in provenance
    QUARANTINED = "quarantined"  # admin review required
    REJECTED = "rejected"


class ContentFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_id: str  # e.g. "injection.ignore_previous", "unicode.zero_width"
    severity: int = Field(ge=1, le=5)
    block_ids: tuple[str, ...] = ()
    detail: str | None = None  # safe summary, no document text


class ContentScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: ContentScanOutcome
    score: float = Field(ge=0.0)
    findings: tuple[ContentFinding, ...] = ()
    rules_version: str


@runtime_checkable
class ContentScanner(Protocol):
    def scan(self, document: CanonicalDocument) -> ContentScanResult: ...
