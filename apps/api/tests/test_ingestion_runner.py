"""Ingestion runner and outbox dispatcher against real PostgreSQL (T3.1, S16).

Covers the S16 test list: outbox event → dispatcher → worker → READY; duplicate delivery has a
single effect; two workers racing for one job → only one runs; a crash between stages resumes from
the checkpoint; retryable vs permanent failures; the dispatcher's least-privilege role.
"""

import asyncio
import json
import uuid
from collections import Counter
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import create_engine, create_sessionmaker
from app.domain.enums import IngestionState
from app.ingestion.errors import PermanentError, RetryableError
from app.ingestion.runner import (
    Checkpoint,
    LeaseBusy,
    RunnerConfig,
    StageContext,
    StageFn,
    _Run,
    run_job,
)
from app.ingestion.state_machine import STAGES
from app.workers.dispatcher import Event, create_dispatcher_engine, dispatch_batch

pytestmark = pytest.mark.integration
S = IngestionState


@pytest.fixture
async def admin(admin_dsn: str, migrated_settings: Settings) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(admin_dsn)
    try:
        yield conn
    finally:
        async with conn.transaction():
            await conn.execute("SET LOCAL app.audit_purge = 'on'")
            await conn.execute("DELETE FROM audit_events")
            await conn.execute("DELETE FROM organizations")
            await conn.execute("DELETE FROM users")
        await conn.close()


@pytest.fixture
async def sessionmaker(
    migrated_settings: Settings, admin: asyncpg.Connection
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(migrated_settings)
    try:
        yield create_sessionmaker(engine)
    finally:
        await engine.dispose()


async def make_job(
    admin: asyncpg.Connection, org: uuid.UUID | None = None
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(org, job, version) with an ingestion.requested outbox event, as T2.4's upload creates."""
    org = org or await admin.fetchval(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', $2) RETURNING id",
        uuid.uuid4(),
        f"acme-{uuid.uuid4().hex[:6]}",
    )
    kb = await admin.fetchval(
        "INSERT INTO knowledge_bases (id, organization_id, name, slug) "
        "VALUES ($1, $2, 'K', $3) RETURNING id",
        uuid.uuid4(),
        org,
        f"k-{uuid.uuid4().hex[:6]}",
    )
    source = await admin.fetchval(
        "INSERT INTO data_sources (id, organization_id, knowledge_base_id, type, name) "
        "VALUES ($1, $2, $3, 'upload', 'U') RETURNING id",
        uuid.uuid4(),
        org,
        kb,
    )
    doc = await admin.fetchval(
        "INSERT INTO documents (id, organization_id, knowledge_base_id, source_id, title) "
        "VALUES ($1, $2, $3, $4, 'D') RETURNING id",
        uuid.uuid4(),
        org,
        kb,
        source,
    )
    version = await admin.fetchval(
        "INSERT INTO document_versions (id, organization_id, document_id, version_number) "
        "VALUES ($1, $2, $3, 1) RETURNING id",
        uuid.uuid4(),
        org,
        doc,
    )
    job = await admin.fetchval(
        "INSERT INTO ingestion_jobs (id, organization_id, document_version_id) "
        "VALUES ($1, $2, $3) RETURNING id",
        uuid.uuid4(),
        org,
        version,
    )
    await admin.execute(
        "INSERT INTO outbox_events (id, organization_id, event_type, aggregate_type, aggregate_id) "
        "VALUES ($1, $2, 'ingestion.requested', 'ingestion_job', $3)",
        uuid.uuid4(),
        org,
        str(job),
    )
    return org, job, version


def counting_stages(counter: Counter[str], **overrides: StageFn) -> dict[IngestionState, StageFn]:
    def make(stage: IngestionState) -> StageFn:
        async def run(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
            counter[stage.value] += 1
            return {"ran": stage.value}

        return run

    stages = {stage: make(stage) for stage in STAGES}
    for name, fn in overrides.items():
        stages[IngestionState(name)] = fn
    return stages


async def job_row(admin: asyncpg.Connection, job: uuid.UUID) -> asyncpg.Record:
    row = await admin.fetchrow("SELECT * FROM ingestion_jobs WHERE id = $1", job)
    assert row is not None
    return row


# --------------------------------------------------------------------------- runner


async def test_job_runs_every_stage_to_ready(
    admin: asyncpg.Connection, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    org, job, version = await make_job(admin)
    counter: Counter[str] = Counter()

    state = await run_job(
        sessionmaker,
        organization_id=org,
        job_id=job,
        worker_id="w1",
        stages=counting_stages(counter),
    )

    assert state is S.READY
    assert counter == Counter({stage.value: 1 for stage in STAGES})
    row = await job_row(admin, job)
    assert (row["state"], row["progress_percent"], row["lease_owner"]) == ("READY", 100, None)
    assert set(json.loads(row["stage_checkpoints"])) == {stage.value for stage in STAGES}
    assert row["completed_at"] is not None
    assert (
        await admin.fetchval(
            "SELECT ingestion_status FROM document_versions WHERE id = $1", version
        )
        == "READY"
    )


async def test_duplicate_delivery_has_a_single_effect(
    admin: asyncpg.Connection, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    org, job, _ = await make_job(admin)
    counter: Counter[str] = Counter()
    stages = counting_stages(counter)

    first = await run_job(
        sessionmaker, organization_id=org, job_id=job, worker_id="w1", stages=stages
    )
    second = await run_job(
        sessionmaker, organization_id=org, job_id=job, worker_id="w2", stages=stages
    )

    assert (first, second) == (S.READY, None)
    assert set(counter.values()) == {1}


async def test_two_workers_racing_run_the_job_once(
    admin: asyncpg.Connection, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    org, job, _ = await make_job(admin)
    counter: Counter[str] = Counter()

    async def slow(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        counter["VALIDATING"] += 1
        await asyncio.sleep(0.2)
        return {}

    stages = counting_stages(counter, VALIDATING=slow)
    results = await asyncio.gather(
        *(
            run_job(sessionmaker, organization_id=org, job_id=job, worker_id=f"w{i}", stages=stages)
            for i in range(4)
        ),
        return_exceptions=True,
    )

    # Exactly one worker ran it; the others saw a live lease (must retry later) or, if they
    # arrived after it finished, a terminal job (nothing to do). None of them ran a stage.
    assert results.count(S.READY) == 1
    assert all(r is None or isinstance(r, LeaseBusy) for r in results if r is not S.READY)
    assert set(counter.values()) == {1}


class SimulatedCrash(BaseException):
    """BaseException: escapes the runner like a killed process would (no failure recorded)."""


async def test_crash_between_stages_resumes_from_the_checkpoint(
    admin: asyncpg.Connection, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    org, job, _ = await make_job(admin)
    counter: Counter[str] = Counter()

    async def crash(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        raise SimulatedCrash

    with pytest.raises(SimulatedCrash):
        await run_job(
            sessionmaker,
            organization_id=org,
            job_id=job,
            worker_id="w1",
            stages=counting_stages(counter, CHUNKING=crash),
        )
    crashed = await job_row(admin, job)
    assert crashed["state"] == "CHUNKING"
    assert "CHUNKING" not in json.loads(crashed["stage_checkpoints"])

    # While the dead worker's lease is live, nobody else may run it, and the redelivered task is
    # told to come back later instead of silently succeeding (review #30)...
    with pytest.raises(LeaseBusy) as busy:
        await run_job(
            sessionmaker,
            organization_id=org,
            job_id=job,
            worker_id="w2",
            stages=counting_stages(counter),
        )
    assert 0 < busy.value.retry_after <= RunnerConfig().lease_seconds + 1
    # ...once it expires, a new worker resumes after the last checkpoint.
    await admin.execute(
        "UPDATE ingestion_jobs SET lease_expires_at = now() - interval '1 second' WHERE id = $1",
        job,
    )
    assert (
        await run_job(
            sessionmaker,
            organization_id=org,
            job_id=job,
            worker_id="w2",
            stages=counting_stages(counter),
        )
        is S.READY
    )

    before_crash = STAGES[: STAGES.index(S.CHUNKING)]
    assert all(counter[s.value] == 1 for s in before_crash), counter  # not re-run
    assert all(counter[s.value] == 1 for s in STAGES[STAGES.index(S.CHUNKING) :]), counter


async def test_retryable_failure_schedules_a_delayed_retry(
    admin: asyncpg.Connection, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    org, job, _ = await make_job(admin)

    async def flaky(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        raise RetryableError("Parser timed out.", code="parser_timeout")

    state = await run_job(
        sessionmaker,
        organization_id=org,
        job_id=job,
        worker_id="w1",
        stages=counting_stages(Counter(), PARSING=flaky),
    )

    assert state is S.FAILED_RETRYABLE
    row = await job_row(admin, job)
    assert (row["attempt_count"], row["error_code"], row["lease_owner"]) == (
        1,
        "parser_timeout",
        None,
    )
    retry = await admin.fetchrow(
        "SELECT available_at FROM outbox_events WHERE aggregate_id = $1 AND payload_json ? 'retry'",
        str(job),
    )
    assert retry is not None
    assert retry["available_at"] > datetime.now(UTC) - timedelta(seconds=1)

    # The retry resumes at PARSING and finishes.
    assert (
        await run_job(
            sessionmaker,
            organization_id=org,
            job_id=job,
            worker_id="w1",
            stages=counting_stages(Counter()),
        )
        is S.READY
    )


async def test_attempts_exhausted_or_permanent_errors_fail_permanently(
    admin: asyncpg.Connection, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    org, job, version = await make_job(admin)

    async def unsupported(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        raise PermanentError("This PDF is encrypted.", code="encrypted_pdf")

    state = await run_job(
        sessionmaker,
        organization_id=org,
        job_id=job,
        worker_id="w1",
        stages=counting_stages(Counter(), PARSING=unsupported),
    )
    assert state is S.FAILED_PERMANENT
    row = await job_row(admin, job)
    assert (row["error_code"], row["error_detail_safe"]) == (
        "encrypted_pdf",
        "This PDF is encrypted.",
    )
    assert (
        await admin.fetchval(
            "SELECT ingestion_status FROM document_versions WHERE id = $1", version
        )
        == "FAILED_PERMANENT"
    )
    # A terminal job is never picked up again.
    assert (
        await run_job(
            sessionmaker,
            organization_id=org,
            job_id=job,
            worker_id="w2",
            stages=counting_stages(Counter()),
        )
        is None
    )

    org2, job2, _ = await make_job(admin)

    async def always_flaky(ctx: StageContext, checkpoint: Checkpoint | None) -> Checkpoint:
        raise RuntimeError("boom with secret detail")

    for _ in range(2):
        last = await run_job(
            sessionmaker,
            organization_id=org2,
            job_id=job2,
            worker_id="w1",
            stages=counting_stages(Counter(), VALIDATING=always_flaky),
            config=RunnerConfig(max_attempts=2),
        )
    assert last is S.FAILED_PERMANENT
    row2 = await job_row(admin, job2)
    assert (row2["attempt_count"], row2["error_code"]) == (2, "internal_error")
    assert "secret" not in (row2["error_detail_safe"] or "")


# --------------------------------------------------------------------------- dispatcher


async def test_dispatcher_publishes_each_event_once_across_orgs(
    admin: asyncpg.Connection, migrated_settings: Settings
) -> None:
    await make_job(admin)
    await make_job(admin)
    engine = create_dispatcher_engine(migrated_settings)
    published: list[Event] = []
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        assert await dispatch_batch(sm, published.append) == 2
        assert await dispatch_batch(sm, published.append) == 0  # nothing left
    finally:
        await engine.dispose()
    assert {e.event_type for e in published} == {"ingestion.requested"}
    assert len({e.organization_id for e in published}) == 2  # cross-tenant, as intended
    assert (
        await admin.fetchval("SELECT count(*) FROM outbox_events WHERE published_at IS NULL") == 0
    )


async def test_publish_failure_backs_off_without_losing_the_event(
    admin: asyncpg.Connection, migrated_settings: Settings
) -> None:
    await make_job(admin)
    engine = create_dispatcher_engine(migrated_settings)

    def broken(event: Event) -> None:
        raise ConnectionError("redis://user:secret@host down")

    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        assert await dispatch_batch(sm, broken) == 0
        assert await dispatch_batch(sm, broken) == 0  # not due yet: backoff respected
    finally:
        await engine.dispose()
    row = await admin.fetchrow(
        "SELECT attempt_count, available_at, published_at, last_error FROM outbox_events"
    )
    assert row is not None
    assert (row["attempt_count"], row["published_at"], row["last_error"]) == (
        1,
        None,
        "ConnectionError",
    )
    assert row["available_at"] >= datetime.now(UTC) - timedelta(seconds=1)


async def test_dispatcher_role_can_only_touch_the_outbox(
    migrated_settings: Settings, admin: asyncpg.Connection
) -> None:
    await make_job(admin)
    dsn = migrated_settings.dispatcher_database_url.get_secret_value().replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM outbox_events") == 1
        # ingestion_jobs/uploads get narrow column grants for the reconciler (T3.6, migration
        # 0008; see test_ingestion_ops.py). Everything else stays out of reach.
        for table in ("documents", "chunks", "organizations", "users", "knowledge_bases"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("DELETE FROM outbox_events")
    finally:
        await conn.close()


async def test_outbox_event_flows_through_dispatcher_to_ready(
    admin: asyncpg.Connection,
    migrated_settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """End to end without a broker: the publisher hands the event straight to the worker task's
    async body, as Celery would."""
    _, job, _ = await make_job(admin)
    delivered: list[Event] = []
    engine = create_dispatcher_engine(migrated_settings)
    try:
        await dispatch_batch(async_sessionmaker(engine, expire_on_commit=False), delivered.append)
    finally:
        await engine.dispose()
    (event,) = delivered
    state = await run_job(
        sessionmaker,
        organization_id=event.organization_id,
        job_id=uuid.UUID(event.aggregate_id),
        worker_id="w1",
        stages=counting_stages(Counter()),
    )
    assert (state, event.aggregate_id) == (S.READY, str(job))
    assert event.payload == {} or "traceparent" in event.payload


async def test_finalization_failure_after_last_checkpoint_resumes_to_ready(
    admin: asyncpg.Connection,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review #30 (HIGH): VERIFYING committed, then finishing failed once. The retry must reach
    READY through the guarded table without re-running any stage."""
    org, job, _ = await make_job(admin)
    counter: Counter[str] = Counter()
    original_finish = _Run.finish
    calls = {"n": 0}

    async def flaky_finish(self: _Run) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection reset while finishing")
        await original_finish(self)

    monkeypatch.setattr(_Run, "finish", flaky_finish)
    stages = counting_stages(counter)

    first = await run_job(
        sessionmaker, organization_id=org, job_id=job, worker_id="w1", stages=stages
    )
    assert first is S.FAILED_RETRYABLE
    row = await job_row(admin, job)
    assert set(json.loads(row["stage_checkpoints"])) == {stage.value for stage in STAGES}

    second = await run_job(
        sessionmaker, organization_id=org, job_id=job, worker_id="w1", stages=stages
    )
    assert second is S.READY
    assert set(counter.values()) == {1}  # no stage ran twice


def test_celery_task_retries_while_another_lease_is_live(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review #30 (HIGH): a late-ack redelivery during a dead worker's live lease is retried after
    the lease expires instead of being acknowledged as a no-op."""
    from app.workers import celery_app as module

    async def busy(organization_id: uuid.UUID, job_id: uuid.UUID) -> str | None:
        raise LeaseBusy(42.0)

    retried: dict[str, float] = {}

    class Retry(Exception):
        pass

    def fake_retry(*, countdown: float, **kwargs: object) -> Exception:
        retried["countdown"] = countdown
        return Retry()

    monkeypatch.setattr(module, "_process_job", busy)
    monkeypatch.setattr(module.process_job, "retry", fake_retry)

    with pytest.raises(Retry):
        module.process_job(str(uuid.uuid4()), str(uuid.uuid4()), {})
    assert 42.0 <= retried["countdown"] <= 47.0
