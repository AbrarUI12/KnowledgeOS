# ruff: noqa: E501, F811  (fixtures imported from test_ingestion_stages; long SQL and fixture lines read better unwrapped in this integration test)
"""Ingestion reliability and operations (T3.6, S20): reconciliation, crash attempts, timeline,
retry / cancel / reindex, inspect mode."""

import json
import uuid
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.domain.enums import IngestionState
from app.ingestion.errors import PermanentError, RetryableError
from app.ingestion.runner import RunnerConfig, run_job
from app.ingestion.stages import STUB_STAGES
from app.ingestion.stages.pipeline import build_stages
from app.workers.dispatcher import create_dispatcher_engine
from app.workers.reconcile import reconcile
from tests.test_ingestion_stages import (  # noqa: F401 (pytest fixtures)
    HANDBOOK,
    POISONED,
    World,
    admin,
    app,
    store,
    world,
)

pytestmark = pytest.mark.integration
S = IngestionState


async def run_reconcile(world: World) -> Any:
    engine = create_dispatcher_engine(world.settings)
    try:
        return await reconcile(
            async_sessionmaker(engine, expire_on_commit=False), world.store, world.settings
        )
    finally:
        await engine.dispose()


async def job_row(admin: asyncpg.Connection, job_id: str | uuid.UUID) -> asyncpg.Record:
    row = await admin.fetchrow("SELECT * FROM ingestion_jobs WHERE id = $1", uuid.UUID(str(job_id)))
    assert row is not None
    return row


def failing(code: str, *, retryable: bool) -> Any:
    def wrap(real: Any) -> Any:
        async def stage(ctx: Any, checkpoint: Any) -> Any:
            if retryable:
                raise RetryableError("Temporary parser outage.", code=code)
            raise PermanentError("The parser rejected this file.", code=code)

        return stage

    return wrap


# --------------------------------------------------------------------------- reconciliation


async def test_reconciler_requeues_stranded_jobs_but_not_live_ones(
    world: World, admin: asyncpg.Connection
) -> None:
    crashed = await world.upload(HANDBOOK, name="crashed.md")
    lost = await world.upload(HANDBOOK, name="lost.md")
    fresh = await world.upload(HANDBOOK, name="fresh.md")
    # crashed: a worker held the lease and died; its request was published long ago.
    await admin.execute(
        "UPDATE ingestion_jobs SET state = 'PARSING', lease_owner = 'dead-worker', "
        "lease_expires_at = now() - interval '1 minute' WHERE id = $1",
        uuid.UUID(crashed["ingestion_job_id"]),
    )
    # lost: never started, its message was published long ago and vanished.
    await admin.execute(
        "UPDATE ingestion_jobs SET created_at = now() - interval '1 hour', updated_at = NULL WHERE id = $1",
        uuid.UUID(lost["ingestion_job_id"]),
    )
    await admin.execute(
        "UPDATE outbox_events SET published_at = now() - interval '1 hour' WHERE aggregate_id = ANY($1::text[])",
        [crashed["ingestion_job_id"], lost["ingestion_job_id"]],
    )
    # fresh: just uploaded, its request is still pending in the outbox → leave it alone.

    report = await run_reconcile(world)

    assert report.requeued_jobs == 2
    for job, expected in ((crashed, 2), (lost, 2), (fresh, 1)):
        count = await admin.fetchval(
            "SELECT count(*) FROM outbox_events WHERE event_type = 'ingestion.requested' AND aggregate_id = $1",
            job["ingestion_job_id"],
        )
        assert count == expected, job
    # Idempotent: the new requests are pending, so a second sweep adds nothing.
    assert (await run_reconcile(world)).requeued_jobs == 0


async def test_reconciler_expires_abandoned_uploads_and_deletes_their_objects(
    world: World, admin: asyncpg.Connection
) -> None:
    start = await world.api.post(
        f"/v1/knowledge-bases/{world.kb}/uploads",
        json={"filename": "never-completed.md", "content_type": "text/markdown", "size_bytes": 10},
        headers=world.h(),
    )
    upload_id = start.json()["upload_id"]
    key = f"{world.org}/{world.kb}/{upload_id}/original"
    await world.store.put(
        world.settings.s3_bucket_quarantine, key, b"0123456789", content_type="text/markdown"
    )
    await admin.execute(
        "UPDATE uploads SET expires_at = now() - interval '2 hours' WHERE id = $1",
        uuid.UUID(upload_id),
    )

    assert (await run_reconcile(world)).expired_uploads == 1
    assert (
        await admin.fetchval("SELECT status FROM uploads WHERE id = $1", uuid.UUID(upload_id))
        == "expired"
    )
    assert not await world.store.exists(world.settings.s3_bucket_quarantine, key)


async def test_reconciler_reminds_long_waiting_approvals_once(
    world: World, admin: asyncpg.Connection
) -> None:
    job = await world.upload(POISONED, name="notes.md")
    assert await world.run(job) is S.PENDING_APPROVAL
    await admin.execute(
        "UPDATE ingestion_jobs SET updated_at = now() - interval '2 days' WHERE id = $1",
        uuid.UUID(job["ingestion_job_id"]),
    )

    assert (await run_reconcile(world)).approval_reminders == 1
    assert (await run_reconcile(world)).approval_reminders == 0


async def test_reconciler_role_cannot_read_job_content(
    world: World, migrated_settings: Settings
) -> None:
    """Column grants: scheduling columns only, never checkpoints or error text."""
    dsn = migrated_settings.dispatcher_database_url.get_secret_value().replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        await conn.fetch("SELECT id, state, lease_expires_at FROM ingestion_jobs")
        for column in ("stage_checkpoints", "error_detail_safe"):
            with pytest.raises(asyncpg.InsufficientPrivilegeError):
                await conn.fetch(f"SELECT {column} FROM ingestion_jobs")  # noqa: S608
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.execute("UPDATE ingestion_jobs SET state = 'READY'")
        with pytest.raises(asyncpg.InsufficientPrivilegeError):
            await conn.fetch("SELECT filename FROM uploads")
    finally:
        await conn.close()


# --------------------------------------------------------------------------- crash attempts & timeline


async def test_a_job_that_keeps_killing_workers_stops(
    world: World, admin: asyncpg.Connection
) -> None:
    job = await world.upload(HANDBOOK)
    await admin.execute(
        "UPDATE ingestion_jobs SET state = 'PARSING', attempt_count = 2, lease_owner = 'dead', "
        "lease_expires_at = now() - interval '1 second' WHERE id = $1",
        uuid.UUID(job["ingestion_job_id"]),
    )

    state = await run_job(
        world.app.state.sessionmaker,
        organization_id=uuid.UUID(world.org),
        job_id=uuid.UUID(job["ingestion_job_id"]),
        worker_id="w-new",
        stages=build_stages(world.deps(), STUB_STAGES),
        config=RunnerConfig(max_attempts=3),
    )

    assert state is S.FAILED_PERMANENT
    row = await job_row(admin, job["ingestion_job_id"])
    assert (row["error_code"], row["attempt_count"]) == ("worker_lost", 4)


async def test_timeline_and_active_version(world: World, admin: asyncpg.Connection) -> None:
    job = await world.upload(HANDBOOK)
    assert await world.run(job) is S.READY

    events = (
        await world.api.get(
            f"/v1/ingestion-jobs/{job['ingestion_job_id']}/events", headers=world.h()
        )
    ).json()
    states = [e["state"] for e in events]
    assert states[0] == "VALIDATING"
    assert states[-1] == "READY"
    assert states.index("MALWARE_SCAN") < states.index("PARSING") < states.index("CHUNKING")
    active = await admin.fetchval(
        "SELECT active_version_id FROM documents WHERE id = $1", uuid.UUID(job["document_id"])
    )
    assert str(active) == job["document_version_id"]


# --------------------------------------------------------------------------- retry / cancel / reindex


async def test_retry_resumes_a_permanently_failed_job_from_its_checkpoints(
    world: World, admin: asyncpg.Connection
) -> None:
    job = await world.upload(HANDBOOK)
    assert (
        await world.run(job, wrap={S.CHUNKING: failing("chunker_crash", retryable=False)})
        is S.FAILED_PERMANENT
    )

    retried = await world.api.post(
        f"/v1/ingestion-jobs/{job['ingestion_job_id']}/retry", headers=world.h()
    )

    assert retried.status_code == 200, retried.text
    new = retried.json()
    assert new["id"] != job["ingestion_job_id"]
    # Starts at the last stage it inherited, so the next transition (→ CHUNKING) is legal.
    assert (new["state"], new["document_version_id"]) == (
        "SECURITY_SCAN",
        job["document_version_id"],
    )
    kept = json.loads((await job_row(admin, new["id"]))["stage_checkpoints"])
    assert "SECURITY_SCAN" in kept
    assert "CHUNKING" not in kept
    assert await world.run({"ingestion_job_id": new["id"]}) is S.READY
    assert (
        await world.api.post(f"/v1/ingestion-jobs/{new['id']}/retry", headers=world.h())
    ).status_code == 409


async def test_retry_of_a_retryable_failure_requeues_the_same_job(
    world: World, admin: asyncpg.Connection
) -> None:
    job = await world.upload(HANDBOOK)
    assert (
        await world.run(job, wrap={S.PARSING: failing("parser_timeout", retryable=True)})
        is S.FAILED_RETRYABLE
    )
    before = await admin.fetchval(
        "SELECT count(*) FROM outbox_events WHERE aggregate_id = $1", job["ingestion_job_id"]
    )

    retried = await world.api.post(
        f"/v1/ingestion-jobs/{job['ingestion_job_id']}/retry", headers=world.h()
    )

    assert retried.json()["id"] == job["ingestion_job_id"]
    after = await admin.fetchval(
        "SELECT count(*) FROM outbox_events WHERE aggregate_id = $1", job["ingestion_job_id"]
    )
    assert after == before + 1


async def test_cancel_stops_a_job_and_a_running_worker_loses_its_lease(
    world: World, admin: asyncpg.Connection
) -> None:
    job = await world.upload(HANDBOOK)
    url = f"/v1/ingestion-jobs/{job['ingestion_job_id']}"

    def cancel_midway(real: Any) -> Any:
        async def stage(ctx: Any, checkpoint: Any) -> Any:
            result = await real(ctx, checkpoint)
            cancelled = await world.api.post(f"{url}/cancel", headers=world.h())
            assert cancelled.status_code == 200, cancelled.text
            return result

        return stage

    assert await world.run(job, wrap={S.NORMALIZING: cancel_midway}) is None  # lease lost, stopped
    row = await job_row(admin, job["ingestion_job_id"])
    assert (row["state"], row["error_code"]) == ("CANCELLED", "cancelled_by_user")
    assert "NORMALIZING" not in json.loads(row["stage_checkpoints"])  # in-flight stage rolled back
    assert await admin.fetchval("SELECT count(*) FROM chunks") == 0
    assert (await world.api.post(f"{url}/cancel", headers=world.h())).status_code == 409


async def test_reindex_rechunks_from_the_canonical_artifact(
    world: World, admin: asyncpg.Connection
) -> None:
    job = await world.upload(HANDBOOK)
    assert await world.run(job) is S.READY
    before = await admin.fetchval(
        "SELECT count(*) FROM chunks WHERE document_version_id = $1",
        uuid.UUID(job["document_version_id"]),
    )

    reindexed = await world.api.post(
        f"/v1/documents/{job['document_id']}/reindex", headers=world.h()
    )

    assert reindexed.status_code == 202, reindexed.text
    new = reindexed.json()
    kept = set(json.loads((await job_row(admin, new["id"]))["stage_checkpoints"]))
    assert kept == {"VALIDATING", "MALWARE_SCAN", "PARSING", "NORMALIZING", "SECURITY_SCAN"}
    assert (
        await world.api.post(f"/v1/documents/{job['document_id']}/reindex", headers=world.h())
    ).status_code == 409
    assert await world.run({"ingestion_job_id": new["id"]}) is S.READY
    after = await admin.fetchval(
        "SELECT count(*) FROM chunks WHERE document_version_id = $1",
        uuid.UUID(job["document_version_id"]),
    )
    assert after == before > 0


async def test_job_list_filters_by_state(world: World) -> None:
    ok = await world.upload(HANDBOOK, name="ok.md")
    bad = await world.upload(HANDBOOK, name="bad.md")
    assert await world.run(ok) is S.READY
    assert await world.run(bad, parsers=()) is S.FAILED_PERMANENT

    failed = (
        await world.api.get(
            f"/v1/knowledge-bases/{world.kb}/ingestion-jobs",
            params={"state": ["FAILED_PERMANENT"]},
            headers=world.h(),
        )
    ).json()
    assert [j["id"] for j in failed["items"]] == [bad["ingestion_job_id"]]
    everything = (
        await world.api.get(f"/v1/knowledge-bases/{world.kb}/ingestion-jobs", headers=world.h())
    ).json()
    assert len(everything["items"]) == 2


# --------------------------------------------------------------------------- inspect mode


async def test_inspect_shows_artifact_chunks_and_findings_to_managers(world: World) -> None:
    job = await world.upload(POISONED, name="notes.md")
    assert await world.run(job) is S.PENDING_APPROVAL
    url = f"/v1/documents/{job['document_id']}/versions/{job['document_version_id']}"
    await world.api.post(f"{url}/approve", json={}, headers=world.h())
    assert await world.run(job) is S.READY

    inspected = await world.api.get(f"{url}/inspect", headers=world.h())

    assert inspected.status_code == 200, inspected.text
    body = inspected.json()
    assert body["canonical"]["title"] == "Notes"
    assert len(body["chunks"]) > 0
    assert body["content_findings"][0]["rule_id"] == "injection.ignore_previous"
