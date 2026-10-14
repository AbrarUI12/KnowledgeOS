"""Bounded, disposable subprocesses for untrusted document conversion (T3.2)."""

import os
import subprocess
import sys
import time
from contextlib import suppress
from pathlib import Path
from threading import Thread

import psutil
import structlog

from app.ingestion.parsing.base import ParserError

logger = structlog.get_logger(__name__)


def child_environment(*, offline: bool = False) -> dict[str, str]:
    allowed = (
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "HOME",
        "USERPROFILE",
        "TMP",
        "TEMP",
        "TMPDIR",
        "HF_HOME",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment.update(
        OMP_NUM_THREADS="2",
        MKL_NUM_THREADS="2",
        OPENBLAS_NUM_THREADS="2",
        NUMEXPR_NUM_THREADS="2",
        TOKENIZERS_PARALLELISM="false",
    )
    if offline:
        environment["HF_HUB_OFFLINE"] = "1"
    return environment


def run_isolated(
    module: str,
    arguments: list[str],
    *,
    timeout_seconds: float,
    memory_bytes: int,
    offline: bool = False,
) -> None:
    if timeout_seconds <= 0 or memory_bytes <= 0:
        raise ValueError("parser limits must be positive")
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", module, *arguments],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        cwd=Path(__file__).resolve().parents[3],
        env=child_environment(offline=offline),
    )
    # Drain continuously so a noisy child cannot block on the pipe. Keep only a bounded tail,
    # not an unbounded disk file that hostile input can fill. Diagnostics stay in server logs.
    tail = bytearray()

    def drain() -> None:
        if process.stderr is None:
            return
        while data := process.stderr.read(4096):
            tail.extend(data)
            del tail[:-8192]

    reader = Thread(target=drain, daemon=True)
    reader.start()
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
        reader.join(timeout=1)
        if process.stderr is not None:
            process.stderr.close()
        if process.returncode:
            logger.warning(
                "parser_child_failed",
                returncode=process.returncode,
                stderr_tail=bytes(tail[-2048:]).decode("utf-8", errors="replace"),
            )
