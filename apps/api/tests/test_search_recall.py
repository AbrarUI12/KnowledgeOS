# ruff: noqa: F811  (fixtures imported from test_ingestion_stages)
"""Filtered HNSW recall (S24): with only a fifth of the chunks readable by the caller, the dense
branch (iterative scan) must still find ≥ 95% of the exact top-k among those it may read."""

import asyncio
import hashlib
import uuid

import asyncpg
import numpy as np
import pytest

from app.db.types import vector_literal
from app.providers.search.base import HybridSearchRequest, SearchScope
from app.providers.search.postgres import PostgresSearchBackend, SearchTuning
from tests.test_ingestion_stages import (  # noqa: F401 (pytest fixtures)
    World,
    admin,
    app,
    store,
    world,
)

pytestmark = [pytest.mark.integration, pytest.mark.slow]
CHUNKS, DIMENSION, CLUSTERS, QUERIES, K = 5_000, 1024, 50, 20, 10


async def hnsw_scans(admin: asyncpg.Connection, at_least: int = 0) -> int:
    """`idx_scan` of the HNSW index, waiting (≤ 15 s) for other sessions to flush their stats."""
    scans = 0
    for _ in range(30):
        await admin.execute("SELECT pg_stat_clear_snapshot()")
        scans = int(
            await admin.fetchval(
                "SELECT idx_scan FROM pg_stat_user_indexes "
                "WHERE indexrelname = 'ix_chunks_embedding_hnsw'"
            )
        )
        if scans >= at_least:
            return scans
        await asyncio.sleep(0.5)
    return scans


async def test_filtered_hnsw_recall_is_at_least_95_percent(
    world: World, admin: asyncpg.Connection
) -> None:
    rng = np.random.default_rng(20261014)
    centers = rng.standard_normal((CLUSTERS, DIMENSION))
    vectors = centers[rng.integers(0, CLUSTERS, CHUNKS)] + 0.6 * rng.standard_normal(
        (CHUNKS, DIMENSION)
    )
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)
    readable = rng.random(CHUNKS) < 0.2

    org, kb = uuid.UUID(world.org), uuid.UUID(world.kb)
    generation, model = await admin.fetchrow(
        "SELECT g.id, g.embedding_model FROM knowledge_bases kb "
        "JOIN index_generations g ON g.id = kb.active_index_generation_id WHERE kb.id = $1",
        kb,
    )
    source = await admin.fetchval("SELECT id FROM data_sources WHERE knowledge_base_id = $1", kb)
    document, version = uuid.uuid4(), uuid.uuid4()
    await admin.execute(
        "INSERT INTO documents (id, organization_id, knowledge_base_id, source_id, title) "
        "VALUES ($1, $2, $3, $4, 'Recall fixture')",
        document,
        org,
        kb,
        source,
    )
    await admin.execute(
        "INSERT INTO document_versions (id, organization_id, document_id, version_number) "
        "VALUES ($1, $2, $3, 1)",
        version,
        org,
        document,
    )
    await admin.execute(
        "UPDATE documents SET active_version_id = $1 WHERE id = $2", version, document
    )
    chunk_ids = [uuid.uuid4() for _ in range(CHUNKS)]
    await admin.executemany(
        "INSERT INTO chunks (id, organization_id, knowledge_base_id, document_id, "
        "document_version_id, index_generation_id, ordinal, block_type, content, embedding_text, "
        "content_hash, token_count, embedding, access_principals) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, 'paragraph', $8, $8, $9, 3, $10::vector, $11)",
        [
            (
                chunk_ids[i],
                org,
                kb,
                document,
                version,
                generation,
                i,
                f"chunk {i}",
                hashlib.sha256(f"chunk {i}".encode()).hexdigest(),
                vector_literal(vectors[i].tolist()),
                ["user:reader"] if readable[i] else ["group:somebody-else"],
            )
            for i in range(CHUNKS)
        ],
    )

    # At 5k rows an exact scan is cheaper and the planner rightly picks it (recall 1.0). Steer it
    # onto the HNSW path to measure what filtered iterative scanning recalls at scale.
    hnsw_only = (("enable_seqscan", "off"), ("enable_sort", "off"))
    backend = PostgresSearchBackend(
        world.app.state.sessionmaker, SearchTuning(planner_settings=hnsw_only)
    )
    scope = SearchScope(
        organization_id=org, knowledge_base_ids=(kb,), principal_tokens=("user:reader",)
    )
    allowed = np.flatnonzero(readable)
    before = await hnsw_scans(admin)
    recalls = []
    for query_center in rng.integers(0, CLUSTERS, QUERIES):
        query = centers[query_center] + 0.6 * rng.standard_normal(DIMENSION)
        query /= np.linalg.norm(query)
        exact = {chunk_ids[i] for i in allowed[np.argsort(-(vectors[allowed] @ query))[:K]]}
        hits = await backend.dense_search(
            HybridSearchRequest(
                scope=scope,
                query="recall",
                query_embedding=tuple(query.tolist()),
                embedding_model=model,
                dense_k=K,
            )
        )
        assert len(hits) == K  # iterative scan keeps going until k readable rows survive
        recalls.append(len(exact & {h.chunk_id for h in hits}) / K)

    print(f" filtered HNSW recall@{K}: {np.mean(recalls):.3f} (min {min(recalls):.2f})")
    assert float(np.mean(recalls)) >= 0.95, recalls

    # And it was the HNSW index that served those real backend queries (runtime role, real SQL,
    # same settings): its scan counter rose by at least one scan per query.
    after = await hnsw_scans(admin, at_least=before + QUERIES)
    assert after - before >= QUERIES, (before, after)
