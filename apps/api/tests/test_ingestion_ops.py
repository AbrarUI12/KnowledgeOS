# ruff: noqa: E501, F811  (fixtures imported from test_ingestion_stages; long SQL and fixture lines read better unwrapped in this integration test)
"""Ingestion reliability and operations (T3.6, S20): reconciliation, crash attempts, timeline,
retry / cancel / reindex, inspect mode."""

import asyncio
import contextlib
import json
import uuid
from typing import Any

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import Settings
from app.domain.enums import TERMINAL_INGESTION_STATES, IngestionState
from app.ingestion.errors import PermanentError, RetryableError
from app.ingestion.runner import RunnerConfig, run_job
from app.ingestion.stages import STUB_STAGES
from app.ingestion.stages.pipeline import build_stages
from app.services import ingestion_jobs
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


async def test_job_list_pages_newest_first_on_request(world: World) -> None:
    jobs = [(await world.upload(HANDBOOK, name=f"d{i}.md"))["ingestion_job_id"] for i in range(3)]
    url = f"/v1/knowledge-bases/{world.kb}/ingestion-jobs"

    async def ids(**params: str | int) -> tuple[list[str], str | None]:
        page = (await world.api.get(url, params=params, headers=world.h())).json()
        return [j["id"] for j in page["items"]], page["next_cursor"]

    oldest, _ = await ids()
    assert oldest == jobs
    first, cursor = await ids(sort="-created_at", limit=2)
    assert first == jobs[::-1][:2]
    rest, end = await ids(sort="-created_at", limit=2, cursor=cursor)
    assert (rest, end) == ([jobs[0]], None)  # keyset continues in the same direction
    bad = await world.api.get(url, params={"sort": "state"}, headers=world.h())
    assert bad.status_code == 422


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


async def join_as(world: World, who: str, role: str) -> None:
    invite = await world.api.post(
        f"/v1/organizations/{world.org}/invitations",
        json={"email": f"{who}@acme.test", "role": role},
        headers={"Authorization": "Bearer alice"},
    )
    assert invite.status_code == 201, invite.text
    token = invite.json()["accept_url"].rsplit("/", 1)[1]
    accepted = await world.api.post(
        f"/v1/invitations/{token}/accept", headers={"Authorization": f"Bearer {who}"}
    )
    assert accepted.status_code == 200, accepted.text


async def test_managing_a_kb_never_overrides_content_acls_in_inspect_mode(
    world: World, admin: asyncpg.Connection
) -> None:
    """Bob is an org admin (kb.manage) but on neither the restricted KB's ACL nor the narrowed
    document's: he may administer them, not read their content (kb_access, Session 23)."""
    await join_as(world, "bob", "admin")
    alice = (await world.api.get("/v1/me", headers=world.h())).json()["user"]["id"]
    job = await world.upload(HANDBOOK)
    assert await world.run(job) is S.READY
    url = f"/v1/documents/{job['document_id']}/versions/{job['document_version_id']}/inspect"
    assert (await world.api.get(url, headers=world.h("bob"))).status_code == 200

    # A document ACL that narrows the (organization) KB to alice.
    await admin.execute(
        "INSERT INTO document_acl (organization_id, document_id, principal_type, principal_id, permission) "
        "VALUES ($1, $2, 'user', $3, 'query')",
        uuid.UUID(world.org), uuid.UUID(job["document_id"]), alice,
    )  # fmt: skip
    denied = await world.api.get(url, headers=world.h("bob"))
    assert denied.status_code == 403
    assert "16 weeks" not in denied.text
    assert (await world.api.get(url, headers=world.h())).status_code == 200
    await admin.execute(
        "DELETE FROM document_acl WHERE document_id = $1", uuid.UUID(job["document_id"])
    )

    # A restricted KB whose ACL names only alice.
    kb_url = f"/v1/knowledge-bases/{world.kb}"
    entry = {"principal_type": "user", "principal_id": alice, "permission": "manage"}
    put = await world.api.put(f"{kb_url}/permissions", json={"entries": [entry]}, headers=world.h())
    assert put.status_code == 200, put.text
    patched = await world.api.patch(kb_url, json={"visibility": "restricted"}, headers=world.h())
    assert patched.status_code == 200, patched.text
    denied = await world.api.get(url, headers=world.h("bob"))
    assert denied.status_code == 403
    assert "16 weeks" not in denied.text
    assert (await world.api.get(url, headers=world.h())).status_code == 200


# --------------------------------------------------------------------------- ordering & concurrency


async def upload_version(world: World, document_id: str, data: bytes) -> dict[str, Any]:
    """A replacement upload: a new version of an existing document."""
    start = await world.api.post(
        f"/v1/knowledge-bases/{world.kb}/uploads",
        json={
            "filename": "handbook.md",
            "content_type": "text/markdown",
            "size_bytes": len(data),
            "document_id": document_id,
        },
        headers=world.h(),
    )
    assert start.status_code == 201, start.text
    upload_id = start.json()["upload_id"]
    await world.store.put(
        world.settings.s3_bucket_quarantine,
        f"{world.org}/{world.kb}/{upload_id}/original",
        data,
        content_type="text/markdown",
    )
    done = await world.api.post(f"/v1/uploads/{upload_id}/complete", json={}, headers=world.h())
    assert done.status_code == 200, done.text
    body: dict[str, Any] = done.json()
    return body


async def test_an_older_version_finishing_last_never_becomes_active(
    world: World, admin: asyncpg.Connection
) -> None:
    v1 = await world.upload(HANDBOOK)
    v2 = await upload_version(world, v1["document_id"], HANDBOOK + b"\nUpdated for 2026.\n")
    assert v2["document_version_id"] != v1["document_version_id"]

    assert await world.run(v2) is S.READY  # the newer version finishes first ...
    assert await world.run(v1) is S.READY  # ... and the older one last

    active = await admin.fetchval(
        "SELECT active_version_id FROM documents WHERE id = $1", uuid.UUID(v1["document_id"])
    )
    assert str(active) == v2["document_version_id"]


async def active_jobs(admin: asyncpg.Connection, version_id: str) -> int:
    count: int = await admin.fetchval(
        "SELECT count(*) FROM ingestion_jobs WHERE document_version_id = $1 "
        "AND state NOT IN ('READY', 'QUARANTINED', 'FAILED_PERMANENT', 'CANCELLED')",
        uuid.UUID(version_id),
    )
    return count


@pytest.fixture
def racing_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force the interleaving a race needs: each "active job exists?" check waits (up to 2 s)
    for a second request to finish its check too, so without serialization both requests pass
    the check before either inserts. With the document lock the second request can't reach
    the check until the first commits, so the first one just times out and carries on."""
    real = ingestion_jobs._active_job_exists
    barrier = asyncio.Barrier(2)

    async def check(session: Any, version_id: uuid.UUID) -> bool:
        found = await real(session, version_id)
        with contextlib.suppress(TimeoutError, asyncio.BrokenBarrierError):
            await asyncio.wait_for(barrier.wait(), timeout=2)
        return found

    monkeypatch.setattr(ingestion_jobs, "_active_job_exists", check)


async def two_failed_histories(
    world: World, *, second_succeeds: bool
) -> tuple[dict[str, Any], str]:
    """Version with a FAILED_PERMANENT job and a retried second job (failed or READY)."""
    first = await world.upload(HANDBOOK)
    crash = {S.CHUNKING: failing("chunker_crash", retryable=False)}
    assert await world.run(first, wrap=crash) is S.FAILED_PERMANENT
    retried = await world.api.post(
        f"/v1/ingestion-jobs/{first['ingestion_job_id']}/retry", headers=world.h()
    )
    second: str = retried.json()["id"]
    expected = S.READY if second_succeeds else S.FAILED_PERMANENT
    wrap = None if second_succeeds else crash
    assert await world.run({"ingestion_job_id": second}, wrap=wrap) is expected
    return first, second


@pytest.mark.usefixtures("racing_checks")
async def test_concurrent_retries_of_different_histories_start_one_job(
    world: World, admin: asyncpg.Connection
) -> None:
    """Two failed jobs of one version, retried at the same time by two people: one wins, the
    other gets 409, and the version never has two active jobs."""
    await join_as(world, "bob", "admin")
    first, second = await two_failed_histories(world, second_succeeds=False)

    results = await asyncio.gather(
        world.api.post(f"/v1/ingestion-jobs/{first['ingestion_job_id']}/retry", headers=world.h()),
        world.api.post(f"/v1/ingestion-jobs/{second}/retry", headers=world.h("bob")),
    )

    assert sorted(r.status_code for r in results) == [200, 409]
    assert await active_jobs(admin, first["document_version_id"]) == 1


@pytest.mark.usefixtures("racing_checks")
async def test_concurrent_retry_and_reindex_start_one_job(
    world: World, admin: asyncpg.Connection
) -> None:
    first, _ = await two_failed_histories(world, second_succeeds=True)

    results = await asyncio.gather(
        world.api.post(f"/v1/ingestion-jobs/{first['ingestion_job_id']}/retry", headers=world.h()),
        world.api.post(f"/v1/documents/{first['document_id']}/reindex", headers=world.h()),
    )

    # Whichever wins (retry answers 200, reindex 202), the other one gets 409.
    retried, reindexed = (r.status_code for r in results)
    assert (retried, reindexed) in {(200, 409), (409, 202)}
    assert await active_jobs(admin, first["document_version_id"]) == 1


async def test_the_database_allows_one_unfinished_job_per_version(
    world: World, admin: asyncpg.Connection
) -> None:
    """Migration 0009's backstop; its state list matches TERMINAL_INGESTION_STATES."""
    indexdef = await admin.fetchval(
        "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_ingestion_jobs_one_active_per_version'"
    )
    assert indexdef is not None
    assert all(f"'{state.value}'" in indexdef for state in TERMINAL_INGESTION_STATES)
    non_terminal = [s for s in IngestionState if s not in TERMINAL_INGESTION_STATES]
    assert not any(f"'{state.value}'" in indexdef for state in non_terminal)

    job = await world.upload(HANDBOOK)
    with pytest.raises(asyncpg.UniqueViolationError):
        await admin.execute(
            "INSERT INTO ingestion_jobs (id, organization_id, document_version_id) VALUES ($1, $2, $3)",
            uuid.uuid4(), uuid.UUID(world.org), uuid.UUID(job["document_version_id"]),
        )  # fmt: skip
