"""Explicit development-only no-op malware scanner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO

from app.core.logging import get_logger
from app.providers.scanning.base import MalwareScanResult, MalwareScanStatus

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class NoopScanner:
    require_malware_scan: bool = False

    async def scan(self, stream: BinaryIO) -> MalwareScanResult:
        del stream
        logger.warning("malware_scan_skipped", required=self.require_malware_scan)
        if self.require_malware_scan:
            return MalwareScanResult(
                status=MalwareScanStatus.ERROR,
                reason="scan_required",
            )
        return MalwareScanResult(
            status=MalwareScanStatus.SKIPPED,
            reason="scan_skipped",
        )
