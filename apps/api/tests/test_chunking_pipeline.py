"""Real Codex libraries through Claude's real runner/persistence, on Testcontainers only."""

import asyncio
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.domain.enums import IngestionState
from app.ingestion.chunking.structure_aware import StructureAwareChunker
from app.ingestion.normalize import normalize
from app.ingestion.parsing.office import OfficeParser
from app.security.content_scanner import RuleContentScanner
from tests.test_ingestion_stages import (
    World,
)
from tests.test_ingestion_stages import (
    admin as admin,
)
from tests.test_ingestion_stages import (
    app as app,
)
from tests.test_ingestion_stages import (
    store as store,
)
from tests.test_ingestion_stages import (
    world as world,
)

pytestmark = pytest.mark.integration
CORPUS = Path(__file__).resolve().parents[3] / "evals/fixtures/corpus/demo"


async def test_real_library_pipeline_persists_nonempty_chunks_and_is_idempotent(
    world: World,
    admin: asyncpg.Connection,
) -> None:
    job = await world.upload(
        b"Eligible employees receive 16 weeks of parental leave (HR-142-B).\n\n"
        b"Manager approval is required.",
        name="handbook.txt",
        content_type="text/plain",
    )
    result = await world.run(
        job,
        parsers=(OfficeParser(),),
        normalize=normalize,
        content_scanner=RuleContentScanner(),
        chunker=StructureAwareChunker(),
    )
    assert result is IngestionState.READY
    version = uuid.UUID(job["document_version_id"])
    rows = await admin.fetch(
        "SELECT ordinal, content, is_parent, parent_chunk_id FROM chunks "
        "WHERE document_version_id=$1 ORDER BY ordinal",
        version,
    )
    assert len(rows) >= 2
    assert any(row["is_parent"] for row in rows)
    children = [row for row in rows if not row["is_parent"]]
    assert children
    assert all(row["parent_chunk_id"] is not None for row in children)
    assert "16 weeks" in " ".join(row["content"] for row in children)
    assert [row["ordinal"] for row in rows] == list(range(len(rows)))
    assert (
        await world.run(
            job,
            parsers=(OfficeParser(),),
            normalize=normalize,
            content_scanner=RuleContentScanner(),
            chunker=StructureAwareChunker(),
        )
        is None
    )
    assert await admin.fetchval(
        "SELECT count(*) FROM chunks WHERE document_version_id=$1", version
    ) == len(rows)
    # Exercise the real CHUNKING transaction again, not just terminal delivery deduplication.
    await admin.execute(
        "UPDATE ingestion_jobs SET state='FAILED_RETRYABLE', "
        "stage_checkpoints=stage_checkpoints-'CHUNKING'-'EMBEDDING'-'INDEXING'-'VERIFYING', "
        "completed_at=NULL WHERE id=$1",
        uuid.UUID(job["ingestion_job_id"]),
    )
    assert (
        await world.run(
            job,
            parsers=(OfficeParser(),),
            normalize=normalize,
            content_scanner=RuleContentScanner(),
            chunker=StructureAwareChunker(),
        )
        is IngestionState.READY
    )
    after = await admin.fetch(
        "SELECT ordinal, content, is_parent FROM chunks "
        "WHERE document_version_id=$1 ORDER BY ordinal",
        version,
    )
    assert [(row["ordinal"], row["content"], row["is_parent"]) for row in after] == [
        (row["ordinal"], row["content"], row["is_parent"]) for row in rows
    ]


async def test_real_poisoned_fixture_is_held_before_any_chunk_persistence(
    world: World,
    admin: asyncpg.Connection,
) -> None:
    path = CORPUS / "acme_eng_notes.txt"
    job = await world.upload(
        await asyncio.to_thread(path.read_bytes), name=path.name, content_type="text/plain"
    )
    result = await world.run(
        job,
        parsers=(OfficeParser(),),
        normalize=normalize,
        content_scanner=RuleContentScanner(),
        chunker=StructureAwareChunker(),
    )
    assert result is IngestionState.PENDING_APPROVAL
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM chunks WHERE document_version_id=$1",
            uuid.UUID(job["document_version_id"]),
        )
        == 0
    )
