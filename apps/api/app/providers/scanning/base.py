"""Malware scanner contract and result types."""

from __future__ import annotations

from enum import StrEnum
from typing import BinaryIO, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class MalwareScanStatus(StrEnum):
    CLEAN = "clean"
    INFECTED = "infected"
    SKIPPED = "skipped"
    ERROR = "error"


class MalwareScanResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: MalwareScanStatus
    threat: str | None = None
    reason: str | None = None


@runtime_checkable
class MalwareScanner(Protocol):
    async def scan(self, stream: BinaryIO) -> MalwareScanResult:
        """Scan an untrusted binary stream and return a fail-closed typed result."""
        ...
