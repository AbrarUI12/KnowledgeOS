"""Malware-scanning providers."""

from app.providers.scanning.base import MalwareScanner, MalwareScanResult, MalwareScanStatus
from app.providers.scanning.clamav import ClamAVScanner
from app.providers.scanning.noop import NoopScanner

__all__ = [
    "ClamAVScanner",
    "MalwareScanResult",
    "MalwareScanStatus",
    "MalwareScanner",
    "NoopScanner",
]
