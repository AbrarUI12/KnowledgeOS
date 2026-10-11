"""Async ClamAV ``clamd`` INSTREAM client."""

from __future__ import annotations

import asyncio
import re
import struct
from contextlib import suppress
from dataclasses import dataclass
from typing import BinaryIO

from app.providers.scanning.base import MalwareScanResult, MalwareScanStatus

_FOUND_RESPONSE = re.compile(r"^[^:]+:\s*(?P<threat>.+)\s+FOUND$")


@dataclass(frozen=True, slots=True)
class ClamAVScanner:
    host: str = "localhost"
    port: int = 3310
    timeout_seconds: float = 30.0
    max_stream_bytes: int = 50 * 1024 * 1024
    chunk_bytes: int = 64 * 1024

    async def scan(self, stream: BinaryIO) -> MalwareScanResult:
        sent = 0
        writer: asyncio.StreamWriter | None = None
        try:
            async with asyncio.timeout(self.timeout_seconds):
                reader, writer = await asyncio.open_connection(self.host, self.port)
                writer.write(b"zINSTREAM\0")
                await writer.drain()
                while chunk := stream.read(self.chunk_bytes):
                    sent += len(chunk)
                    if sent > self.max_stream_bytes:
                        writer.write(struct.pack("!I", 0))
                        await writer.drain()
                        return MalwareScanResult(
                            status=MalwareScanStatus.ERROR,
                            reason="scan_size_limit_exceeded",
                        )
                    writer.write(struct.pack("!I", len(chunk)))
                    writer.write(chunk)
                    await writer.drain()
                writer.write(struct.pack("!I", 0))
                await writer.drain()
                raw_response = await reader.readuntil(b"\0")
        except TimeoutError:
            return MalwareScanResult(status=MalwareScanStatus.ERROR, reason="scan_timeout")
        except (ConnectionError, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            return MalwareScanResult(status=MalwareScanStatus.ERROR, reason="scanner_unavailable")
        finally:
            if writer is not None:
                writer.close()
                with suppress(ConnectionError, OSError):
                    await writer.wait_closed()

        response = raw_response.rstrip(b"\0").decode("utf-8", errors="replace")
        if response.endswith(" OK"):
            return MalwareScanResult(status=MalwareScanStatus.CLEAN)
        if match := _FOUND_RESPONSE.match(response):
            return MalwareScanResult(
                status=MalwareScanStatus.INFECTED,
                threat=match.group("threat"),
            )
        return MalwareScanResult(status=MalwareScanStatus.ERROR, reason="invalid_scanner_response")
