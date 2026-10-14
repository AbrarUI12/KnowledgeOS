"""Outbox dispatcher (S16, ADR-005): `python -m app.workers.dispatcher`.

Loop: lock a batch of due, unpublished events with `FOR UPDATE SKIP LOCKED` (so several dispatchers
can run side by side without double-publishing), hand each one to the publisher, then mark it
published, or count the failure and push `available_at` back with jittered backoff.

Connects as `knowledgeos_dispatcher`: the only role with cross-tenant access, and only to
`outbox_events` (migration 0006). Delivery is at-least-once: a crash after publishing but before
commit re-publishes, so every consumer is idempotent (the ingestion runner's lease and
checkpoints make duplicate deliveries a no-op).
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.db.models import OutboxEvent
from app.ingestion.errors import backoff_seconds

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Event:
    id: uuid.UUID
    organization_id: uuid.UUID
    event_type: str
    aggregate_type: str
    aggregate_id: str
    payload: dict[str, Any]


Publisher = Callable[[Event], None]

# event_type -> (Celery task name, queue)
ROUTES: dict[str, tuple[str, str]] = {
    "ingestion.requested": ("ingestion.process_job", "ingestion"),
    "acl.changed": ("acl.sync_knowledge_base", "maintenance"),
}


async def dispatch_batch(
    sessionmaker: async_sessionmaker[AsyncSession], publish: Publisher, *, batch_size: int = 100
) -> int:
    """Publish one batch of due events. Returns how many were published."""
    published = 0
    async with sessionmaker() as session, session.begin():
        # Database time throughout: comparing a host clock with DB-set timestamps drifts.
        now = cast(datetime, await session.scalar(select(func.now())))
        rows = await session.scalars(
            select(OutboxEvent)
            .where(OutboxEvent.published_at.is_(None), OutboxEvent.available_at <= now)
            .order_by(OutboxEvent.created_at)
            .limit(batch_size)
            .with_for_update(skip_locked=True)
        )
        for row in rows:
            event = Event(
                id=row.id,
                organization_id=row.organization_id,
                event_type=row.event_type,
                aggregate_type=row.aggregate_type,
                aggregate_id=row.aggregate_id,
                payload=dict(row.payload_json or {}),
            )
            try:
                publish(event)
            except Exception as exc:
                row.attempt_count += 1
                row.available_at = now + timedelta(seconds=backoff_seconds(row.attempt_count))
                row.last_error = type(exc).__name__  # no messages: they can embed hosts/secrets
                logger.warning(
                    "outbox_publish_failed", event_id=str(row.id), error_type=type(exc).__name__
                )
                continue
            row.published_at = now
            published += 1
    return published


def celery_publisher() -> Publisher:
    from app.workers.celery_app import celery_app

    def publish(event: Event) -> None:
        route = ROUTES.get(event.event_type)
        if route is None:
            logger.warning("outbox_event_unrouted", event_type=event.event_type)
            return  # nothing consumes it yet; mark it published so it doesn't block the queue
        task, queue = route
        celery_app.send_task(
            task,
            kwargs={
                "organization_id": str(event.organization_id),
                "aggregate_id": event.aggregate_id,
                "payload": event.payload,
            },
            queue=queue,
            task_id=str(event.id),  # a redelivered event keeps its task id
        )

    return publish


def create_dispatcher_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.dispatcher_database_url.get_secret_value(), pool_size=2, pool_pre_ping=True
    )


async def run_forever(settings: Settings) -> None:
    engine = create_dispatcher_engine(settings)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    publish = celery_publisher()
    logger.info("dispatcher_started")
    try:
        while True:
            count = await dispatch_batch(
                sessionmaker, publish, batch_size=settings.dispatcher_batch_size
            )
            if count == 0:
                await asyncio.sleep(settings.dispatcher_poll_seconds)
    finally:
        await engine.dispose()


def main() -> None:
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)
    asyncio.run(run_forever(settings))


if __name__ == "__main__":
    main()
