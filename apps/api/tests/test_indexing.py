# ruff: noqa: E501, F811  (fixtures imported from test_ingestion_stages; long SQL reads better unwrapped)
"""Indexing (T4.2, S22-S23): embeddings, full text, identifiers, ACL materialization and its
propagation, index generations, required indexes."""

import hashlib
import json
import re
import uuid
from collections.abc import Sequence
from typing import Any, ClassVar

import asyncpg
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import Settings
from app.db.tenant import tenant_session
from app.db.types import vector_literal
from app.domain.enums import IngestionState
from app.ingestion import stages
from app.ingestion.canonical import CanonicalDocument
from app.ingestion.chunking.types import ChunkDraft
from app.ingestion.normalize import normalize
from app.ingestion.stages import embedding_provider
from app.providers.embeddings.base import EmbeddingUnavailableError
from app.services.chunk_acl import sync_knowledge_base
from tests.fakes import FakeChunker, FakeEmbeddingProvider
from tests.test_ingestion_ops import join_as
from tests.test_ingestion_stages import (  # noqa: F401 (pytest fixtures)
    World,
    admin,
    app,
    store,
    world,
)

pytestmark = pytest.mark.integration
S = IngestionState
POLICY = (
    b"# Parental leave policy\n\n"
    b"Eligible employees receive sixteen weeks of fully paid parental leave under policy "
    b"HR-142-B, starting from the first day of the child's arrival.\n\n"
    b"Requests must be submitted to the people team at least thirty days before the planned "
    b"start date of the leave.\n"
)


async def chunks_of(admin: asyncpg.Connection, version_id: str) -> list[asyncpg.Record]:
    rows: list[asyncpg.Record] = await admin.fetch(
        "SELECT ordinal, is_parent, content, embedding IS NOT NULL AS has_vector, "
        "search_vector IS NOT NULL AS has_text, search_vector::text AS tsv, fts_config::text AS cfg, "
        "access_principals, identifiers FROM chunks WHERE document_version_id = $1 ORDER BY ordinal",
        uuid.UUID(version_id),
    )
    return rows


async def job_row(admin: asyncpg.Connection, job: dict[str, Any]) -> asyncpg.Record:
    row = await admin.fetchrow(
        "SELECT state, error_code, stage_checkpoints FROM ingestion_jobs WHERE id = $1",
        uuid.UUID(job["ingestion_job_id"]),
    )
    assert row is not None
    return row


async def me(world: World, who: str = "alice") -> str:
    user_id: str = (await world.api.get("/v1/me", headers=world.h(who))).json()["user"]["id"]
    return user_id


# --------------------------------------------------------------------------- indexing


async def test_a_ready_document_is_embedded_full_text_indexed_and_acl_tagged(
    world: World, admin: asyncpg.Connection
) -> None:
    job = await world.upload(POLICY, name="parental-leave.md")
    assert await world.run(job, normalize=normalize) is S.READY

    rows = await chunks_of(admin, job["document_version_id"])
    assert len(rows) == 2
    assert all(r["has_vector"] and r["has_text"] for r in rows)
    assert {r["cfg"] for r in rows} == {"english"}  # detected language, not `simple`
    assert all(r["access_principals"] == [f"org:{world.org}"] for r in rows)
    # Title (A), section path (B) and body (C) weights.
    assert all(re.search(r":\d+A", r["tsv"]) and re.search(r":\d+B", r["tsv"]) for r in rows)

    version = uuid.UUID(job["document_version_id"])
    lexical = await admin.fetch(
        "SELECT content FROM chunks WHERE document_version_id = $1 "
        "AND search_vector @@ websearch_to_tsquery(fts_config, 'paid leave weeks')",
        version,
    )
    assert [r["content"] for r in lexical] == [rows[0]["content"]]
    query = await FakeEmbeddingProvider().embed_query("weeks of paid parental leave")
    nearest = await admin.fetchval(
        "SELECT content FROM chunks WHERE document_version_id = $1 ORDER BY embedding <=> $2::vector LIMIT 1",
        version,
        vector_literal(query),
    )
    assert "sixteen weeks" in nearest
    checkpoints = json.loads((await job_row(admin, job))["stage_checkpoints"])
    assert checkpoints["EMBEDDING"]["embedded"] == 2
    assert checkpoints["VERIFYING"]["self_query"] == "ok"


class ParentChunker(FakeChunker):
    """One parent section chunk over the fake children, which also carry identifiers."""

    def chunk(self, document: CanonicalDocument) -> list[ChunkDraft]:
        children = super().chunk(document)
        content = "\n\n".join(c.content for c in children)
        parent = children[0].model_copy(
            update={
                "ordinal": 0,
                "is_parent": True,
                "content": content,
                "embedding_text": content,
                "content_hash": hashlib.sha256(content.encode()).hexdigest(),
            }
        )
        return [
            parent,
            *(
                c.model_copy(
                    update={
                        "ordinal": i + 1,
                        "parent_ordinal": 0,
                        "identifiers": re.findall(r"\b[A-Z]{2,}-\d+(?:-[A-Z])?\b", c.content),
                    }
                )
                for i, c in enumerate(children)
            ),
        ]


async def test_parents_are_context_only_and_identifiers_are_kept(
    world: World, admin: asyncpg.Connection
) -> None:
    job = await world.upload(POLICY)
    assert await world.run(job, chunker=ParentChunker()) is S.READY

    parent, *children = await chunks_of(admin, job["document_version_id"])
    assert parent["is_parent"]
    assert not parent["has_vector"]
    assert not parent["has_text"]
    assert parent["access_principals"] == [f"org:{world.org}"]  # context is authorized too
    assert all(c["has_vector"] and c["has_text"] for c in children)
    assert children[0]["identifiers"] == ["HR-142-B"]
    assert children[1]["identifiers"] == []


# --------------------------------------------------------------------------- embeddings


class CountingEmbedder(FakeEmbeddingProvider):
    def __init__(self) -> None:
        super().__init__()
        self.texts = 0

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts += len(texts)
        return await super().embed_documents(texts)


async def test_vectors_are_reused_inside_the_organization_only(
    world: World, admin: asyncpg.Connection
) -> None:
    embedder = CountingEmbedder()
    first = await world.upload(POLICY)
    assert await world.run(first, embedder=embedder) is S.READY
    assert embedder.texts == 2

    again = await world.upload(POLICY)  # same text in the same organization
    assert await world.run(again, embedder=embedder) is S.READY
    assert embedder.texts == 2  # nothing re-embedded
    reused = json.loads((await job_row(admin, again))["stage_checkpoints"])["EMBEDDING"]
    assert (reused["embedded"], reused["reused"]) == (0, 2)

    # Another organization never borrows Acme's vectors.
    owner = {"Authorization": "Bearer alice"}
    other_org = (
        await world.api.post(
            "/v1/organizations", json={"name": "Globex", "slug": "globex"}, headers=owner
        )
    ).json()["id"]
    other_kb = (
        await world.api.post(
            "/v1/knowledge-bases",
            json={"name": "HR"},
            headers={**owner, "X-Organization-Id": other_org},
        )
    ).json()["id"]
    globex = World(world.app, world.api, world.store, other_org, other_kb)
    elsewhere = await globex.upload(POLICY)
    assert await globex.run(elsewhere, embedder=embedder) is S.READY
    assert embedder.texts == 4


class OtherModel(FakeEmbeddingProvider):
    model_id = "some-other-model"


class Unavailable(FakeEmbeddingProvider):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise EmbeddingUnavailableError("model server down")


class RejectsOutput(FakeEmbeddingProvider):
    """Like T4.1's EmbeddingDimensionError: a ValueError is a configuration problem."""

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise ValueError("Expected dimension 1024, received 768.")


class WrongDimension(FakeEmbeddingProvider):
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.5, 0.5, 0.5] for _ in texts]


@pytest.mark.parametrize(
    ("deps", "state", "code"),
    [
        ({"embedder": OtherModel()}, S.FAILED_PERMANENT, "embedding_model_mismatch"),
        ({"embedder": WrongDimension()}, S.FAILED_PERMANENT, "embedding_dimension_mismatch"),
        ({"embedder": RejectsOutput()}, S.FAILED_PERMANENT, "embedding_dimension_mismatch"),
        ({"embedder": Unavailable()}, S.FAILED_RETRYABLE, "embedding_unavailable"),
        (
            {"embedder": None, "require_embeddings": True},
            S.FAILED_RETRYABLE,
            "embedding_unavailable",
        ),
    ],
    ids=["other-model", "wrong-dimension", "provider-rejects", "unavailable", "no-provider"],
)
async def test_embedding_never_substitutes_or_stores_bad_vectors(
    world: World, admin: asyncpg.Connection, deps: dict[str, Any], state: S, code: str
) -> None:
    job = await world.upload(POLICY)

    assert await world.run(job, **deps) is state

    row = await job_row(admin, job)
    assert row["error_code"] == code
    assert not any(r["has_vector"] for r in await chunks_of(admin, job["document_version_id"]))


async def test_local_development_without_a_provider_indexes_full_text_only(
    world: World, admin: asyncpg.Connection
) -> None:
    job = await world.upload(POLICY)

    assert await world.run(job, embedder=None, require_embeddings=False) is S.READY

    rows = await chunks_of(admin, job["document_version_id"])
    assert all(r["has_text"] and not r["has_vector"] for r in rows)
    checkpoints = json.loads((await job_row(admin, job))["stage_checkpoints"])
    assert checkpoints["EMBEDDING"]["skipped"] == "no_embedding_provider"
    assert checkpoints["VERIFYING"]["self_query"] == "skipped"


class RecordingEmbedder(FakeEmbeddingProvider):
    """Stands in for a T4.1 class to capture the constructor arguments the registry passes."""

    built: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(kwargs["dimension"])
        RecordingEmbedder.built.append(kwargs)


def test_the_provider_is_named_by_config_and_never_guessed(
    migrated_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(ValidationError, match="embedding_provider"):
        Settings(_env_file=None, embedding_provider="mystery")
    with pytest.raises(ValidationError, match="EMBEDDING_BASE_URL is required"):
        Settings(_env_file=None, embedding_provider="openai_compatible")

    monkeypatch.setitem(
        stages._EMBEDDERS, "openai_compatible", ("tests.test_indexing", "RecordingEmbedder")
    )
    monkeypatch.setattr(stages, "_embedders", {})
    RecordingEmbedder.built.clear()
    endpoint = migrated_settings.model_copy(
        update={
            "embedding_provider": "openai_compatible",
            "embedding_base_url": "http://embeddings.internal:8080/v1",
            "embedding_api_key": SecretStr("not-a-real-key"),
        }
    )
    first, again = embedding_provider(endpoint), embedding_provider(endpoint)
    assert first is not None
    assert first is again  # one instance per process and configuration
    assert RecordingEmbedder.built == [
        {
            "model_id": endpoint.embedding_model,
            "dimension": 1024,
            "max_batch": endpoint.embedding_batch_size,
            "base_url": "http://embeddings.internal:8080/v1",
            "is_external": False,
            "api_key": "not-a-real-key",
        }
    ]


# --------------------------------------------------------------------------- ACL propagation


async def sync(world: World) -> int:
    org = uuid.UUID(world.org)
    async with tenant_session(world.app.state.sessionmaker, org) as session:
        return await sync_knowledge_base(session, org, uuid.UUID(world.kb))


async def test_acl_changes_propagate_to_every_chunk_and_are_confirmed(
    world: World, admin: asyncpg.Connection
) -> None:
    alice = await me(world)
    job = await world.upload(POLICY)
    assert await world.run(job) is S.READY
    kb_url = f"/v1/knowledge-bases/{world.kb}"
    entry = {"principal_type": "user", "principal_id": alice, "permission": "manage"}
    await world.api.put(f"{kb_url}/permissions", json={"entries": [entry]}, headers=world.h())
    await world.api.patch(kb_url, json={"visibility": "restricted"}, headers=world.h())
    pending = (await world.api.get(f"{kb_url}/permissions", headers=world.h())).json()
    assert pending["propagated_at"] is None
    events = await admin.fetchval(
        "SELECT count(*) FROM outbox_events WHERE event_type = 'acl.changed' AND aggregate_id = $1",
        world.kb,
    )
    assert events == 1  # visibility (the creator's manage entry was already there)

    assert await sync(world) == 2
    rows = await chunks_of(admin, job["document_version_id"])
    assert all(r["access_principals"] == [f"user:{alice}"] for r in rows)
    confirmed = (await world.api.get(f"{kb_url}/permissions", headers=world.h())).json()
    assert confirmed["propagated_at"] is not None
    assert await sync(world) == 0  # idempotent: nothing left to rewrite

    # A document ACL narrows just that document's chunks.
    hr = (
        await world.api.post(
            f"/v1/organizations/{world.org}/groups", json={"name": "HR"}, headers=world.h()
        )
    ).json()["id"]
    await admin.execute(
        "INSERT INTO document_acl (organization_id, document_id, principal_type, principal_id, permission) "
        "VALUES ($1, $2, 'group', $3, 'query')",
        uuid.UUID(world.org), uuid.UUID(job["document_id"]), hr,
    )  # fmt: skip
    entries = [entry, {"principal_type": "group", "principal_id": hr, "permission": "query"}]
    await world.api.put(f"{kb_url}/permissions", json={"entries": entries}, headers=world.h())
    assert await sync(world) == 2
    rows = await chunks_of(admin, job["document_version_id"])
    assert all(r["access_principals"] == [f"group:{hr}"] for r in rows)


async def test_a_group_membership_change_is_effective_without_reindexing(
    world: World, admin: asyncpg.Connection
) -> None:
    """Chunks name the group, not its members: adding Bob to HR opens the document to him at once,
    and not a single chunk is rewritten (S23)."""
    await join_as(world, "bob", "member")
    alice, bob = await me(world), await me(world, "bob")
    hr = (
        await world.api.post(
            f"/v1/organizations/{world.org}/groups", json={"name": "HR"}, headers=world.h()
        )
    ).json()["id"]
    kb_url = f"/v1/knowledge-bases/{world.kb}"
    entries = [
        {"principal_type": "user", "principal_id": alice, "permission": "manage"},
        {"principal_type": "group", "principal_id": hr, "permission": "query"},
    ]
    await world.api.put(f"{kb_url}/permissions", json={"entries": entries}, headers=world.h())
    await world.api.patch(kb_url, json={"visibility": "restricted"}, headers=world.h())
    job = await world.upload(POLICY)
    assert await world.run(job) is S.READY
    version = uuid.UUID(job["document_version_id"])

    async def readable_by_bob() -> int:
        groups = await admin.fetch(
            "SELECT group_id FROM group_memberships WHERE user_id = $1", uuid.UUID(bob)
        )
        tokens = [f"user:{bob}", "role:member", f"org:{world.org}"] + [
            f"group:{g['group_id']}" for g in groups
        ]
        count: int = await admin.fetchval(
            "SELECT count(*) FROM chunks WHERE document_version_id = $1 AND access_principals && $2::text[]",
            version,
            tokens,
        )
        return count

    before = await chunks_of(admin, job["document_version_id"])
    assert await readable_by_bob() == 0
    added = await world.api.post(
        f"/v1/organizations/{world.org}/groups/{hr}/members",
        json={"user_id": bob},
        headers=world.h(),
    )
    assert added.status_code == 204, added.text
    assert await readable_by_bob() == len(before)
    assert await chunks_of(admin, job["document_version_id"]) == before


# --------------------------------------------------------------------------- generations & indexes


async def test_index_generations_record_the_exact_model(world: World) -> None:
    await join_as(world, "bob", "member")
    url = f"/v1/knowledge-bases/{world.kb}/index-generations"

    generations = (await world.api.get(url, headers=world.h())).json()

    assert [
        (g["generation_number"], g["status"], g["embedding_model"], g["embedding_dimension"])
        for g in generations
    ] == [(1, "active", FakeEmbeddingProvider.model_id, 1024)]
    assert (await world.api.get(url, headers=world.h("bob"))).status_code == 403


async def test_required_indexes_exist_and_dense_queries_use_hnsw(
    world: World, admin: asyncpg.Connection
) -> None:
    names = {
        r["indexname"]
        for r in await admin.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename IN ('chunks', 'documents')"
        )
    }
    assert {
        "ix_chunks_embedding_hnsw",
        "ix_chunks_search_vector",
        "ix_chunks_access_principals",
        "ix_chunks_identifiers",
        "ix_chunks_org_kb_generation",
        "ix_chunks_document_version",
        "ix_documents_title_trgm",
    } <= names

    job = await world.upload(POLICY)
    assert await world.run(job) is S.READY
    query = vector_literal(await FakeEmbeddingProvider().embed_query("paid leave"))
    async with admin.transaction():
        await admin.execute("SET LOCAL enable_seqscan = off")
        plan = "\n".join(
            r[0]
            for r in await admin.fetch(
                "EXPLAIN SELECT id FROM chunks ORDER BY embedding <=> $1::vector LIMIT 5", query
            )
        )
    assert "ix_chunks_embedding_hnsw" in plan
