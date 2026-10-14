# ruff: noqa: E501  (long SQL reads better unwrapped)
"""Worker crash recovery against the real local stack (S20, Demo 12).

Opt-in: it drives the shared Docker Compose stack (`make up` + worker/dispatcher) and kills the
worker container, so it only runs with KOS_CRASH_TEST=1, normally through
`scripts/demo_worker_crash.sh`, which starts the worker with slow stages and short leases.

Scenario: a document is processed once cleanly (reference), then again while the worker is
`docker kill`ed mid-stage and restarted. The killed task isn't redelivered quickly (Redis only does
so after its visibility timeout), so the reconciler finds the job stranded once the dead worker's
lease expires and re-queues it; the job resumes from its last checkpoint and must reach READY
with exactly the reference chunk count, the crash counted as an attempt.
"""

import asyncio
import os
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import asyncpg
import boto3
import pytest
from botocore.config import Config as BotoConfig

pytestmark = [
    pytest.mark.crash,
    pytest.mark.skipif(os.environ.get("KOS_CRASH_TEST") != "1", reason="set KOS_CRASH_TEST=1"),
]

REPO = Path(__file__).resolve().parents[3]
DSN = os.environ.get("KOS_CRASH_DSN", "postgresql://postgres:postgres@localhost:5433/knowledgeos")
CONTENT = (REPO / "evals/fixtures/corpus/demo/acme_support_faq.md").read_bytes()
TERMINAL = {"READY", "FAILED_PERMANENT", "QUARANTINED", "CANCELLED"}
CHUNKS_OF_JOB = (
    "SELECT count(*) FROM chunks c JOIN ingestion_jobs j ON j.document_version_id = c.document_version_id "
    "WHERE j.id = $1"
)


def compose(*args: str) -> None:
    subprocess.run(["docker", "compose", *args], cwd=REPO, check=True, capture_output=True)  # noqa: S603, S607


def s3() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000"),
        aws_access_key_id=os.environ.get("S3_ACCESS_KEY_ID", "kos_minio"),
        aws_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY", "kos_minio_dev_secret"),
        region_name="us-east-1",
        config=BotoConfig(s3={"addressing_style": "path"}),
    )


async def seed(
    conn: asyncpg.Connection, org: uuid.UUID, kb: uuid.UUID, source: uuid.UUID
) -> uuid.UUID:
    """One uploaded-and-completed document version, exactly as T2.4 leaves it."""
    doc, version, upload, job = (uuid.uuid4() for _ in range(4))
    key = f"{org}/{kb}/{upload}/original"
    s3().put_object(Bucket="kos-quarantine", Key=key, Body=CONTENT, ContentType="text/markdown")
    await conn.execute(
        "INSERT INTO documents (id, organization_id, knowledge_base_id, source_id, title) VALUES ($1,$2,$3,$4,'FAQ')",
        doc, org, kb, source,
    )  # fmt: skip
    await conn.execute(
        "INSERT INTO document_versions (id, organization_id, document_id, version_number, object_key, mime_type, size_bytes) "
        "VALUES ($1,$2,$3,1,$4,'text/markdown',$5)",
        version, org, doc, key, len(CONTENT),
    )  # fmt: skip
    await conn.execute(
        "INSERT INTO uploads (id, organization_id, knowledge_base_id, document_id, document_version_id, filename, "
        "declared_mime, declared_size, object_key, status, expires_at) "
        "VALUES ($1,$2,$3,$4,$5,'faq.md','text/markdown',$6,$7,'completed', now())",
        upload, org, kb, doc, version, len(CONTENT), key,
    )  # fmt: skip
    await conn.execute(
        "INSERT INTO ingestion_jobs (id, organization_id, document_version_id) VALUES ($1,$2,$3)",
        job,
        org,
        version,
    )
    await conn.execute(
        "INSERT INTO outbox_events (id, organization_id, event_type, aggregate_type, aggregate_id) "
        "VALUES ($1,$2,'ingestion.requested','ingestion_job',$3)",
        uuid.uuid4(), org, str(job),
    )  # fmt: skip
    return job


async def wait_for(
    conn: asyncpg.Connection, job: uuid.UUID, done: Callable[[asyncpg.Record], bool], within: float
) -> asyncpg.Record:
    deadline = time.monotonic() + within
    row = None
    while time.monotonic() < deadline:
        row = await conn.fetchrow(
            "SELECT state, attempt_count FROM ingestion_jobs WHERE id = $1", job
        )
        if row is not None and done(row):
            return row
        await asyncio.sleep(0.5)
    raise AssertionError(f"job {job} didn't get there within {within}s (last: {row})")


async def test_killed_worker_resumes_and_matches_a_clean_run() -> None:
    conn = await asyncpg.connect(DSN)
    org, kb, generation, source = (uuid.uuid4() for _ in range(4))
    try:
        await conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Crash demo', $2)",
            org,
            f"crash-{uuid.uuid4().hex[:6]}",
        )
        await conn.execute(
            "INSERT INTO knowledge_bases (id, organization_id, name, slug) VALUES ($1,$2,'KB','kb')",
            kb,
            org,
        )
        await conn.execute(
            "INSERT INTO index_generations (id, organization_id, knowledge_base_id, generation_number, status, "
            "embedding_provider, embedding_model, embedding_dimension, chunker_name) "
            "VALUES ($1,$2,$3,1,'active','sentence_transformers','Qwen/Qwen3-Embedding-0.6B',1024,'structure_aware')",
            generation, org, kb,
        )  # fmt: skip
        await conn.execute(
            "UPDATE knowledge_bases SET active_index_generation_id = $1 WHERE id = $2",
            generation,
            kb,
        )
        await conn.execute(
            "INSERT INTO data_sources (id, organization_id, knowledge_base_id, type, name) VALUES ($1,$2,$3,'upload','Uploads')",
            source, org, kb,
        )  # fmt: skip

        # Reference: a clean run.
        clean = await seed(conn, org, kb, source)
        clean_final = await wait_for(conn, clean, lambda r: r["state"] in TERMINAL, within=180)
        assert clean_final["state"] == "READY"
        clean_chunks = await conn.fetchval(CHUNKS_OF_JOB, clean)

        # Crash run: kill the worker once the job is past its first checkpoints.
        crashed = await seed(conn, org, kb, source)
        mid_run = {"PARSING", "NORMALIZING", "SECURITY_SCAN", "CHUNKING"}
        await wait_for(conn, crashed, lambda r: r["state"] in mid_run, within=120)
        compose("kill", "worker")
        compose("start", "worker")
        final = await wait_for(conn, crashed, lambda r: r["state"] in TERMINAL, within=300)

        assert final["state"] == "READY"
        assert final["attempt_count"] >= 1  # the lost lease was counted
        assert await conn.fetchval(CHUNKS_OF_JOB, crashed) == clean_chunks
    finally:
        async with conn.transaction():
            await conn.execute("SET LOCAL app.audit_purge = 'on'")
            await conn.execute("DELETE FROM organizations WHERE id = $1", org)
        await conn.close()
