"""Bounded, disposable subprocesses for untrusted document conversion (T3.2)."""

import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path

import psutil

from app.ingestion.parsing.base import ParserError


def run_isolated(
    module: str, arguments: list[str], *, timeout_seconds: float, memory_bytes: int
) -> None:
    if timeout_seconds <= 0 or memory_bytes <= 0:
        raise ValueError("parser limits must be positive")
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", module, *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=Path(__file__).resolve().parents[3],
    )
    root = psutil.Process(process.pid)
    deadline = time.monotonic() + timeout_seconds
    try:
        while process.poll() is None:
            if time.monotonic() >= deadline:
                raise ParserError(
                    "Document parsing timed out.", code="parser_timeout", retryable=True
                )
            try:
                family = [root, *root.children(recursive=True)]
                resident = sum(child.memory_info().rss for child in family if child.is_running())
            except psutil.NoSuchProcess:
                resident = 0
            if resident > memory_bytes:
                raise ParserError("Parser exceeded its memory limit.", code="parser_memory_limit")
            time.sleep(0.02)
        if process.returncode:
            raise ParserError("Document conversion failed.", code="parser_failed")
    finally:
        try:
            descendants = root.children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        for child in reversed(descendants):
            with suppress(psutil.NoSuchProcess):
                child.kill()
        if process.poll() is None:
            process.kill()
        process.wait()
