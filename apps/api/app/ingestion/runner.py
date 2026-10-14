"""Ingestion job runner: lease, checkpointed stages, retries (S16, ADR-005, plan §14.1, §34.2).

A job spans many transactions, so the job row carries a **lease** (`lease_owner`,
`lease_expires_at`) claimed with a conditional UPDATE: of two workers racing for one job, exactly
one wins. Each stage then runs in two transactions:

1. *transition* (short): move the job to the stage, if this worker still holds the lease;
2. *work*: run the stage under a transaction-scoped advisory lock on the document version and, in
   the same transaction, store the stage's checkpoint, again only if the lease is still ours.
   Stage effects and checkpoint commit together or not at all.

A stage that already has a checkpoint is skipped, so a crashed job resumes where it stopped once
its lease expires. Postgres is the source of truth for progress, never Celery (ADR-005).
"""

import uuid
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import structlog
from sqlalchemy import bindparam, func, or_, select, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.base import new_uuid
from app.db.models import AuditEvent, DocumentVersion, IngestionJob
from app.db.tenant import tenant_session
from app.domain.enums import IngestionState
from app.ingestion.errors import (
    APPROVAL_HOLD,
    Quarantined,
    RetryableError,
    StageError,
    backoff_seconds,
)
from app.ingestion.state_machine import PROGRESS, STAGES, ensure_transition
from app.services import outbox

logger = structlog.get_logger(__name__)

Checkpoint = dict[str, Any]


@dataclass(frozen=True, slots=True)
class StageContext:
    session: AsyncSession  # the work transaction, already in the job's tenant context
    organization_id: uuid.UUID
    job_id: uuid.UUID
    document_version_id: uuid.UUID
    attempt: int
    heartbeat: Callable[[], Awaitable[None]]
    # Side effects that must only happen once the stage's transaction has committed (e.g.
    # deleting the quarantine copy after promotion). Run best-effort; leftovers are swept.
    after_commit: list[Callable[[], Awaitable[None]]] = field(default_factory=list)


StageFn = Callable[[StageContext, Checkpoint | None], Awaitable[Checkpoint]]


@dataclass(frozen=True, slots=True)
class RunnerConfig:
    lease_seconds: int = 300
    max_attempts: int = 5
    backoff_base_seconds: float = 10.0
    backoff_cap_seconds: float = 900.0


class LeaseLost(RuntimeError):
    """Another worker took over (our lease expired). Stop without writing anything."""


class LeaseBusy(RuntimeError):
    """The job is runnable but another worker's lease is still live (e.g. Celery redelivered the
    task of a worker that died mid-stage). The caller must retry after `retry_after` seconds,
    never drop the delivery, or the job would be stranded until the lease expires unattended."""

    def __init__(self, retry_after: float) -> None:
        super().__init__(f"job lease busy; retry in {retry_after:.0f}s")
        self.retry_after = retry_after


# States in which a worker may pick the job up.
_RUNNABLE = {IngestionState.RECEIVED, IngestionState.FAILED_RETRYABLE, *STAGES}


def _now() -> Any:
    """Database time. Leases are compared across workers on different hosts, so host clocks
    (and the host-vs-database skew of a Docker VM) must never decide who owns a job."""
    return func.now()


@dataclass
class _Run:
    sessionmaker: async_sessionmaker[AsyncSession]
    organization_id: uuid.UUID
    job_id: uuid.UUID
    worker_id: str
    config: RunnerConfig
    document_version_id: uuid.UUID = field(default_factory=uuid.uuid4)
    attempt: int = 0

    def _mine(self) -> Any:
        return (IngestionJob.id == self.job_id) & (IngestionJob.lease_owner == self.worker_id)

    async def claim(self) -> Checkpoint | None:
        """Take the lease if it's free (or expired) and the job is runnable."""
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            now = _now()
            row = (
                await session.execute(
                    update(IngestionJob)
                    .where(
                        IngestionJob.id == self.job_id,
                        IngestionJob.organization_id == self.organization_id,
                        IngestionJob.state.in_([s.value for s in _RUNNABLE]),
                        or_(
                            IngestionJob.lease_expires_at.is_(None),
                            IngestionJob.lease_expires_at < now,
                        ),
                    )
                    .values(
                        lease_owner=self.worker_id,
                        lease_expires_at=now + timedelta(seconds=self.config.lease_seconds),
                        heartbeat_at=now,
                        started_at=func.coalesce(IngestionJob.started_at, now),
                        updated_at=now,
                    )
                    .returning(
                        IngestionJob.document_version_id,
                        IngestionJob.attempt_count,
                        IngestionJob.stage_checkpoints,
                    )
                )
            ).one_or_none()
        if row is None:
            return None
        self.document_version_id, self.attempt = row.document_version_id, row.attempt_count
        return dict(row.stage_checkpoints or {})

    async def lease_remaining(self) -> float | None:
        """Seconds left on someone else's live lease if the job is runnable, else None."""
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            row = (
                await session.execute(
                    select(
                        IngestionJob.state,
                        func.extract("epoch", IngestionJob.lease_expires_at - func.now()),
                    ).where(
                        IngestionJob.id == self.job_id,
                        IngestionJob.organization_id == self.organization_id,
                    )
                )
            ).one_or_none()
        if row is None or IngestionState(row[0]) not in _RUNNABLE or row[1] is None:
            return None
        return max(float(row[1]), 0.0)

    async def heartbeat(self) -> None:
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            now = _now()
            result = await session.execute(
                update(IngestionJob)
                .where(self._mine())
                .values(
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self.config.lease_seconds),
                )
            )
            if result.rowcount == 0:  # type: ignore[attr-defined]
                raise LeaseLost

    async def _set_state(
        self, session: AsyncSession, target: IngestionState, **values: Any
    ) -> None:
        current = await session.scalar(
            select(IngestionJob.state).where(self._mine()).with_for_update()
        )
        if current is None:
            raise LeaseLost
        if IngestionState(current) != target:
            ensure_transition(IngestionState(current), target)
        await session.execute(
            update(IngestionJob)
            .where(self._mine())
            .values(state=target.value, updated_at=_now(), **values)
        )
        await session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == self.document_version_id)
            .values(ingestion_status=target.value)
        )

    async def run_stage(
        self, stage: IngestionState, fn: StageFn, checkpoint: Checkpoint | None
    ) -> Checkpoint:
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            await self._set_state(
                session, stage, stage=stage.value, progress_percent=PROGRESS[stage]
            )
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            # One writer per (version, index generation) for write stages.
            await session.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtextextended(f"ingest:{self.document_version_id}", 0)
                    )
                )
            )
            context = StageContext(
                session=session,
                organization_id=self.organization_id,
                job_id=self.job_id,
                document_version_id=self.document_version_id,
                attempt=self.attempt,
                heartbeat=self.heartbeat,
            )
            result = await fn(context, checkpoint) or {}
            now = _now()
            stored = await session.execute(
                update(IngestionJob)
                .where(self._mine())
                .values(
                    # Merge, not overwrite: earlier stages' checkpoints stay intact.
                    stage_checkpoints=IngestionJob.stage_checkpoints.op("||")(
                        bindparam("checkpoint", {stage.value: result}, type_=JSONB)
                    ),
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self.config.lease_seconds),
                )
            )
            if stored.rowcount == 0:  # type: ignore[attr-defined]
                raise LeaseLost  # rolls back the stage's effects too
            if result.get("hold") == APPROVAL_HOLD:
                # Park in the SAME transaction as the checkpoint: a crash can never leave a
                # stored hold whose job carries on without approval.
                await self._park_for_approval(session)
        for effect in context.after_commit:
            try:
                await effect()
            except Exception as exc:  # leftovers are harmless and swept later (T3.6)
                logger.warning("ingestion_after_commit_failed", error_type=type(exc).__name__)
        return result

    async def _park_for_approval(self, session: AsyncSession) -> None:
        await self._set_state(
            session, IngestionState.PENDING_APPROVAL, lease_owner=None, lease_expires_at=None
        )
        await session.execute(
            update(DocumentVersion)
            .where(DocumentVersion.id == self.document_version_id)
            .values(approval_status="pending")
        )

    async def is_approved(self) -> bool:
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            status = await session.scalar(
                select(DocumentVersion.approval_status).where(
                    DocumentVersion.id == self.document_version_id
                )
            )
        return status == "approved"

    async def finish(self) -> None:
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            now = _now()
            current = await session.scalar(select(IngestionJob.state).where(self._mine()))
            if current is not None and IngestionState(current) is not STAGES[-1]:
                # Every checkpoint exists but the job isn't at the last stage: finalization failed
                # after VERIFYING committed (e.g. FAILED_RETRYABLE). Re-enter the last stage
                # through the guarded table instead of jumping straight to READY.
                await self._set_state(session, STAGES[-1], stage=STAGES[-1].value)
            await self._set_state(
                session,
                IngestionState.READY,
                stage=None,
                progress_percent=100,
                completed_at=now,
                lease_owner=None,
                lease_expires_at=None,
                error_code=None,
                error_detail_safe=None,
            )

    async def hold_for_approval(self) -> None:
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            await self._park_for_approval(session)

    async def quarantine(self, error: Quarantined) -> IngestionState:
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            await self._set_state(
                session,
                IngestionState.QUARANTINED,
                error_code=error.code,
                error_detail_safe=error.safe_detail[:500],
                lease_owner=None,
                lease_expires_at=None,
                completed_at=_now(),
            )
            session.add(
                AuditEvent(
                    id=new_uuid(),
                    organization_id=self.organization_id,
                    actor_type="system",
                    action="document.quarantined",
                    resource_type="document_version",
                    resource_id=str(self.document_version_id),
                    metadata_json={"job_id": str(self.job_id), "code": error.code},
                )
            )
        return IngestionState.QUARANTINED

    async def fail(self, error: StageError) -> IngestionState:
        attempts = self.attempt + 1
        retry = isinstance(error, RetryableError) and attempts < self.config.max_attempts
        target = IngestionState.FAILED_RETRYABLE if retry else IngestionState.FAILED_PERMANENT
        async with tenant_session(self.sessionmaker, self.organization_id) as session:
            await self._set_state(
                session,
                target,
                attempt_count=attempts,
                error_code=error.code,
                error_detail_safe=error.safe_detail[:500],
                lease_owner=None,
                lease_expires_at=None,
                completed_at=None if retry else _now(),
            )
            if retry:
                delay = backoff_seconds(
                    attempts,
                    base=self.config.backoff_base_seconds,
                    cap=self.config.backoff_cap_seconds,
                )
                await outbox.emit_system(
                    session,
                    self.organization_id,
                    "ingestion.requested",
                    "ingestion_job",
                    self.job_id,
                    {"document_version_id": str(self.document_version_id), "retry": attempts},
                    available_at=_now() + timedelta(seconds=delay),
                )
        return target


async def run_job(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    worker_id: str,
    stages: Mapping[IngestionState, StageFn],
    config: RunnerConfig | None = None,
) -> IngestionState | None:
    """Run (or resume) one job. Returns the state it ended in, or None if there's nothing to run
    (terminal, or waiting for approval). Raises `LeaseBusy` if another worker's lease is still
    live, so the caller retries after it expires instead of dropping the work."""
    run = _Run(sessionmaker, organization_id, job_id, worker_id, config or RunnerConfig())
    checkpoints = await run.claim()
    if checkpoints is None:
        remaining = await run.lease_remaining()
        if remaining is not None:
            raise LeaseBusy(remaining + 1)
        return None
    log = logger.bind(job_id=str(job_id), worker_id=worker_id)
    try:
        for stage in STAGES:
            if stage.value in checkpoints:
                # Done before a crash or retry. A stored approval hold still binds until a
                # reviewer approves: resuming must never walk past it.
                if checkpoints[stage.value].get("hold") == APPROVAL_HOLD and not (
                    await run.is_approved()
                ):
                    await run.hold_for_approval()
                    log.info("ingestion_job_pending_approval", stage=stage.value, resumed=True)
                    return IngestionState.PENDING_APPROVAL
                continue
            checkpoints[stage.value] = await run.run_stage(stage, stages[stage], None)
            if checkpoints[stage.value].get("hold") == APPROVAL_HOLD:
                log.info("ingestion_job_pending_approval", stage=stage.value)
                return IngestionState.PENDING_APPROVAL
        await run.finish()
        log.info("ingestion_job_ready")
        return IngestionState.READY
    except LeaseLost:
        log.warning("ingestion_lease_lost")
        return None
    except Quarantined as exc:
        log.warning("ingestion_job_quarantined", error_code=exc.code)
        return await run.quarantine(exc)
    except StageError as exc:
        log.warning("ingestion_stage_failed", error_code=exc.code)
        return await run.fail(exc)
    except Exception as exc:  # unexpected bug or dependency failure: retry, never leak details
        log.exception("ingestion_stage_crashed", error_type=type(exc).__name__)
        return await run.fail(RetryableError("Unexpected processing error.", code="internal_error"))
