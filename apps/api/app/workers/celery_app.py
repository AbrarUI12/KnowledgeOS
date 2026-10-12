"""Celery application and tasks (S16, plan §34.2).

Reliability settings: late acks + reject on worker loss (a task is redelivered if the worker dies),
prefetch 1 (long ingestion tasks don't hoard), JSON only, time limits. Postgres, not Celery state,
is the source of truth: tasks only carry IDs.

Tasks are sync; each run creates its own async engine inside `asyncio.run` and disposes it, so no
connection or event loop crosses a fork (Celery's prefork pool; run workers in Docker on Windows).
"""

import asyncio
import os
import socket
import uuid
from typing import Any

from celery import Celery

from app.core.config import get_settings

QUEUES = ("ingestion", "sync", "maintenance", "eval", "llm")

settings = get_settings()

celery_app = Celery(
    "knowledgeos",
    broker=(settings.celery_broker_url or settings.redis_url).get_secret_value(),
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    accept_content=["json"],
    task_ignore_result=True,
    task_soft_time_limit=900,
    task_time_limit=960,
    task_default_queue="maintenance",
    broker_connection_retry_on_startup=True,
)


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def _process_job(organization_id: uuid.UUID, job_id: uuid.UUID) -> str | None:
    from app.db.session import create_engine, create_sessionmaker
    from app.ingestion.runner import RunnerConfig, run_job
    from app.ingestion.stages import default_stages

    engine = create_engine(settings)
    try:
        state = await run_job(
            create_sessionmaker(engine),
            organization_id=organization_id,
            job_id=job_id,
            worker_id=_worker_id(),
            stages=default_stages(),
            config=RunnerConfig(
                lease_seconds=settings.ingestion_lease_seconds,
                max_attempts=settings.ingestion_max_attempts,
            ),
        )
        return state.value if state else None
    finally:
        await engine.dispose()


@celery_app.task(name="ingestion.process_job", queue="ingestion")  # type: ignore[untyped-decorator]
def process_job(organization_id: str, aggregate_id: str, payload: dict[str, Any]) -> str | None:
    return asyncio.run(_process_job(uuid.UUID(organization_id), uuid.UUID(aggregate_id)))


@celery_app.task(name="acl.sync_knowledge_base", queue="maintenance")  # type: ignore[untyped-decorator]
def sync_knowledge_base_acl(
    organization_id: str, aggregate_id: str, payload: dict[str, Any]
) -> None:
    """Re-materialize chunk ACLs after a KB permission change. Implemented in T4.2 (S23)."""
    return None
