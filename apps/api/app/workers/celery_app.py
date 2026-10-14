"""Celery application and tasks (S16, plan §34.2).

Reliability settings: late acks + reject on worker loss (a task is redelivered if the worker dies),
prefetch 1 (long ingestion tasks don't hoard), JSON only, time limits. Postgres, not Celery state,
is the source of truth: tasks only carry IDs.

Tasks are sync; each run creates its own async engine inside `asyncio.run` and disposes it, so no
connection or event loop crosses a fork (Celery's prefork pool; run workers in Docker on Windows).
"""

import asyncio
import os
import random
import socket
import uuid
from typing import Any

from celery import Celery

from app.core.config import get_settings
from app.workers.schedules import beat_schedule

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
    # Redis redelivers an unacknowledged (late-ack) task only after this timeout, e.g. after a
    # worker is killed. Must exceed the longest task (task_time_limit) or long tasks get delivered
    # twice; the reconciler (maintenance.reconcile) is the fast path for crashed work.
    broker_transport_options={"visibility_timeout": 1200},
)


celery_app.conf.beat_schedule = beat_schedule(settings)


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


async def _process_job(organization_id: uuid.UUID, job_id: uuid.UUID) -> str | None:
    from app.db.session import create_engine, create_sessionmaker
    from app.ingestion.runner import RunnerConfig, run_job
    from app.ingestion.stages import default_stages

    store = _object_store()

    engine = create_engine(settings)
    try:
        state = await run_job(
            create_sessionmaker(engine),
            organization_id=organization_id,
            job_id=job_id,
            worker_id=_worker_id(),
            stages=default_stages(settings, store),
            config=RunnerConfig(
                lease_seconds=settings.ingestion_lease_seconds,
                max_attempts=settings.ingestion_max_attempts,
            ),
        )
        return state.value if state else None
    finally:
        await engine.dispose()


# A live lease means another worker owns the job, or a dead worker's lease hasn't expired yet
# (late-ack redelivery after a crash). Retry until it expires rather than acking a no-op.
LEASE_RETRY_LIMIT = 50


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True, name="ingestion.process_job", queue="ingestion", max_retries=LEASE_RETRY_LIMIT
)
def process_job(
    self: Any, organization_id: str, aggregate_id: str, payload: dict[str, Any]
) -> str | None:
    from app.ingestion.runner import LeaseBusy

    try:
        return asyncio.run(_process_job(uuid.UUID(organization_id), uuid.UUID(aggregate_id)))
    except LeaseBusy as busy:
        raise self.retry(countdown=busy.retry_after + random.uniform(0, 5)) from busy  # noqa: S311


@celery_app.task(  # type: ignore[untyped-decorator]
    name="acl.sync_knowledge_base",
    queue="maintenance",
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=8,
)
def sync_knowledge_base_acl(
    organization_id: str, aggregate_id: str, payload: dict[str, Any]
) -> int:
    """Re-materialize chunk ACLs after a KB visibility or permission change (`acl.changed`).
    Idempotent: a redelivered or repeated event rewrites nothing that's already right."""
    return asyncio.run(_sync_acl(uuid.UUID(organization_id), uuid.UUID(aggregate_id)))


async def _sync_acl(organization_id: uuid.UUID, kb_id: uuid.UUID) -> int:
    from app.db.session import create_engine, create_sessionmaker
    from app.db.tenant import tenant_session
    from app.services.chunk_acl import sync_knowledge_base

    engine = create_engine(settings)
    try:
        async with tenant_session(create_sessionmaker(engine), organization_id) as session:
            return await sync_knowledge_base(session, organization_id, kb_id)
    finally:
        await engine.dispose()


def _object_store() -> Any:
    from app.providers.storage import S3ObjectStore

    return S3ObjectStore(
        endpoint_url=settings.s3_endpoint_url,
        public_endpoint_url=settings.s3_public_endpoint_url,
        region_name=settings.s3_region,
        access_key_id=settings.s3_access_key_id.get_secret_value(),
        secret_access_key=settings.s3_secret_access_key.get_secret_value(),
        force_path_style=settings.s3_force_path_style,
        connect_timeout_seconds=settings.s3_connect_timeout_seconds,
        read_timeout_seconds=settings.s3_read_timeout_seconds,
        max_attempts=settings.s3_max_attempts,
    )


async def _reconcile() -> dict[str, int]:
    from dataclasses import asdict

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.workers.dispatcher import create_dispatcher_engine
    from app.workers.reconcile import reconcile

    engine = create_dispatcher_engine(settings)
    try:
        report = await reconcile(
            async_sessionmaker(engine, expire_on_commit=False), _object_store(), settings
        )
        return asdict(report)
    finally:
        await engine.dispose()


@celery_app.task(name="maintenance.reconcile", queue="maintenance")  # type: ignore[untyped-decorator]
def reconcile_task() -> dict[str, int]:
    """Re-queue stranded jobs, expire abandoned uploads, remind waiting approvals (S20)."""
    return asyncio.run(_reconcile())
