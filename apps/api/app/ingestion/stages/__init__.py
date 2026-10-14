"""Ingestion stage registry (S16-S19).

Every stage starts as a **stub** (no-op) so a job can always reach READY end to end. T3.5 adds the
real VALIDATING / MALWARE_SCAN / PARSING / NORMALIZING / SECURITY_SCAN / CHUNKING stages
(`pipeline.py`); T4.2 adds EMBEDDING / INDEXING / VERIFYING. A stage is
`async (ctx, checkpoint) -> checkpoint` and must be idempotent: it may run again after a crash
before its checkpoint was stored.

`default_stages()` wires the real stages from the libraries that exist. File validation and
malware scanning are always real. Parsing → chunking switch on only when *all four* libraries are
importable (parser, normalizer, content scanner, chunker: Codex's T3.2-T3.4), so a half-wired
pipeline can never index content that skipped the content-security scan.
"""

import asyncio
import importlib
from collections.abc import Mapping
from typing import Any

import structlog

from app.core.config import Environment, Settings
from app.domain.enums import IngestionState
from app.ingestion.runner import Checkpoint, StageContext, StageFn
from app.ingestion.state_machine import STAGES
from app.providers.scanning.base import MalwareScanner
from app.providers.storage import ObjectStore

logger = structlog.get_logger(__name__)


async def _stub(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
    return {"stub": True}


STUB_STAGES: Mapping[IngestionState, StageFn] = dict.fromkeys(STAGES, _stub)

# Optional extra parsers, registered after the required one when importable (first match wins).
_EXTRA_PARSERS: tuple[tuple[str, str], ...] = (("app.ingestion.parsing.office", "OfficeParser"),)

# (module, attribute) of each required library implementation, discovered at runtime.
_COMPONENTS: dict[str, tuple[str, str]] = {
    "parser": ("app.ingestion.parsing.docling", "DoclingParser"),
    "normalize": ("app.ingestion.normalize", "normalize"),
    "content_scanner": ("app.security.content_scanner", "RuleContentScanner"),
    "chunker": ("app.ingestion.chunking.structure_aware", "StructureAwareChunker"),
}


def _discover() -> dict[str, Any] | None:
    found: dict[str, Any] = {}
    for name, (module, attribute) in _COMPONENTS.items():
        try:
            found[name] = getattr(importlib.import_module(module), attribute)
        except (ImportError, AttributeError):
            logger.info("ingestion_component_missing", component=name)
            return None
    return found


def _extra_parsers() -> list[Any]:
    parsers = []
    for module, attribute in _EXTRA_PARSERS:
        try:
            parsers.append(getattr(importlib.import_module(module), attribute)())
        except (ImportError, AttributeError):
            logger.info("ingestion_parser_missing", parser=attribute)
    return parsers


def malware_scanner(settings: Settings) -> MalwareScanner:
    from app.providers.scanning.clamav import ClamAVScanner
    from app.providers.scanning.noop import NoopScanner

    if settings.malware_scanner == "none":
        return NoopScanner(require_malware_scan=settings.require_malware_scan)
    return ClamAVScanner(
        host=settings.clamav_host,
        port=settings.clamav_port,
        max_stream_bytes=settings.clamav_max_stream_bytes,
    )


def _with_debug_delay(
    settings: Settings, stages: dict[IngestionState, StageFn]
) -> dict[IngestionState, StageFn]:
    """Local/test only: slow every stage down so crash tests can kill a worker mid-stage."""
    delay = settings.ingestion_debug_stage_delay_seconds
    if delay <= 0 or settings.environment not in {Environment.LOCAL, Environment.TEST}:
        return stages

    def slow(fn: StageFn) -> StageFn:
        async def stage(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
            await asyncio.sleep(delay)
            return await fn(ctx, checkpoint)

        return stage

    return {state: slow(fn) for state, fn in stages.items()}


def default_stages(settings: Settings, store: ObjectStore) -> Mapping[IngestionState, StageFn]:
    """The stage implementations workers run."""
    return _with_debug_delay(settings, _real_stages(settings, store))


def _real_stages(settings: Settings, store: ObjectStore) -> dict[IngestionState, StageFn]:
    from app.ingestion.stages import pipeline

    stages: dict[IngestionState, StageFn] = dict(STUB_STAGES)
    scanner = malware_scanner(settings)
    components = _discover()
    if components is None:
        partial = pipeline.StageDeps(
            settings=settings,
            store=store,
            malware_scanner=scanner,
            parsers=(),
            normalize=_identity,
            content_scanner=_Missing(),
            chunker=_Missing(),
        )
        stages[IngestionState.VALIDATING] = pipeline.validating(partial)
        stages[IngestionState.MALWARE_SCAN] = pipeline.malware_scan(partial)
        return stages
    deps = pipeline.StageDeps(
        settings=settings,
        store=store,
        malware_scanner=scanner,
        parsers=(components["parser"](), *_extra_parsers()),
        normalize=components["normalize"],
        content_scanner=components["content_scanner"](),
        chunker=components["chunker"](),
    )
    return pipeline.build_stages(deps, stages)


def _identity(document: Any) -> Any:
    return document


class _Missing:
    """Placeholder for a library that isn't installed yet; never called (its stages stay stubs)."""

    config: Any = None

    def scan(self, document: Any) -> Any:
        raise RuntimeError("library not installed")

    def chunk(self, document: Any) -> Any:
        raise RuntimeError("library not installed")


__all__ = ["STUB_STAGES", "default_stages", "malware_scanner"]
