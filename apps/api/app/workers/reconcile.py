"""Ingestion reconciliation sweeper (S20, T3.6): `maintenance.reconcile`, run by Celery beat.

The safety net behind the lease/retry machinery, for work that got lost rather than failed:

1. **Stranded jobs**: runnable jobs whose lease expired (worker died) or that never started
   (message lost), with no pending or recent `ingestion.requested` event → a new outbox event
   re-queues them. The runner's lease and checkpoints make an extra delivery harmless, and a
   recovered lease counts as an attempt, so a job that keeps killing workers stops.
2. **Abandoned uploads**: still `pending` after their presigned window (plus grace) → `expired`;
   the quarantine object is deleted after the transaction commits.
3. **Waiting approvals**: `PENDING_APPROVAL` longer than the reminder interval → an
   `approval.reminder` event (status center), at most one per interval per job.

Runs as `knowledgeos_dispatcher` (cross-tenant, column-limited grants; migration 0008, ADR-004)
and only ever inserts outbox rows or flips an upload's status, never touching tenant content.
"""

import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import cast

import structlog
from sqlalchemy import ColumnElement, Exists, Text, and_, exists, func, or_, select, update
from sqlalchemy import cast as sql_cast
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.base import new_uuid
from app.db.models import IngestionJob, OutboxEvent, Upload
from app.domain.enums import IngestionState
from app.ingestion.state_machine import STAGES
from app.providers.storage import ObjectStore
from app.services.outbox import new_traceparent

logger = structlog.get_logger(__name__)

_RUNNABLE = [
    IngestionState.RECEIVED.value,
    IngestionState.FAILED_RETRYABLE.value,
    *(stage.value for stage in STAGES),
]


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    requeued_jobs: int = 0
    expired_uploads: int = 0
    approval_reminders: int = 0


def _event(
    organization_id: uuid.UUID, event_type: str, job_id: uuid.UUID, reason: str
) -> OutboxEvent:
    return OutboxEvent(
        id=new_uuid(),
        organization_id=organization_id,
        event_type=event_type,
        aggregate_type="ingestion_job",
        aggregate_id=str(job_id),
        payload_json={"traceparent": new_traceparent(), "reason": reason},
    )


def _job_event_exists(event_type: str, *conditions: ColumnElement[bool]) -> Exists:
    return exists().where(
        OutboxEvent.aggregate_id == sql_cast(IngestionJob.id, Text),
        OutboxEvent.event_type == event_type,
        *conditions,
    )


async def reconcile(
    sessionmaker: async_sessionmaker[AsyncSession],
    store: ObjectStore,
    settings: Settings,
    *,
    batch_size: int = 200,
) -> ReconcileReport:
    stale = timedelta(seconds=settings.reconcile_stale_seconds)
    reminder_every = timedelta(seconds=settings.approval_reminder_seconds)
    deletions: list[str] = []

    async with sessionmaker() as session, session.begin():
        now = cast(datetime, await session.scalar(select(func.now())))  # database time

        # 1. Stranded jobs: lease expired, or never leased and old, with no pending/recent event.
        recent_request = _job_event_exists(
            "ingestion.requested",
            or_(OutboxEvent.published_at.is_(None), OutboxEvent.published_at > now - stale),
        )
        never_started = and_(
            IngestionJob.lease_owner.is_(None),
            func.coalesce(IngestionJob.updated_at, IngestionJob.created_at) < now - stale,
        )
        stranded = (
            await session.execute(
                select(IngestionJob.id, IngestionJob.organization_id)
                .where(
                    IngestionJob.state.in_(_RUNNABLE),
                    or_(IngestionJob.lease_expires_at < now, never_started),
                    ~recent_request,
                )
                .limit(batch_size)
            )
        ).all()
        for job_id, organization_id in stranded:
            session.add(_event(organization_id, "ingestion.requested", job_id, "reconcile"))

        # 2. Abandoned uploads.
        abandoned = (
            await session.execute(
                select(Upload.id, Upload.object_key)
                .where(Upload.status == "pending", Upload.expires_at < now - stale)
                .limit(batch_size)
                .with_for_update(skip_locked=True)
            )
        ).all()
        if abandoned:
            await session.execute(
                update(Upload)
                .where(Upload.id.in_([row.id for row in abandoned]))
                .values(status="expired")
            )
            deletions = [row.object_key for row in abandoned]

        # 3. Long-waiting approvals, reminded at most once per interval.
        recent_reminder = _job_event_exists(
            "approval.reminder", OutboxEvent.created_at > now - reminder_every
        )
        waiting = (
            await session.execute(
                select(IngestionJob.id, IngestionJob.organization_id)
                .where(
                    IngestionJob.state == IngestionState.PENDING_APPROVAL.value,
                    func.coalesce(IngestionJob.updated_at, IngestionJob.created_at)
                    < now - reminder_every,
                    ~recent_reminder,
                )
                .limit(batch_size)
            )
        ).all()
        for job_id, organization_id in waiting:
            session.add(_event(organization_id, "approval.reminder", job_id, "approval_waiting"))

    # After commit the uploads are `expired`, so deleting their objects is safe. A failed delete
    # only leaves an orphan object in the quarantine bucket (its lifecycle rule removes it).
    for key in deletions:
        try:
            await store.delete(settings.s3_bucket_quarantine, key)
        except Exception as exc:
            logger.warning("reconcile_upload_delete_failed", error_type=type(exc).__name__)

    report = ReconcileReport(len(stranded), len(abandoned), len(waiting))
    if report != ReconcileReport():
        logger.info("ingestion_reconciled", **asdict(report))
    return report
