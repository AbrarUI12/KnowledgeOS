# ruff: noqa: F811  (fixtures imported from test_ingestion_stages; long SQL reads better unwrapped)
"""Search API and query runs (T4.6, S25-S26) through the real HTTP stack, the PostgreSQL search
backend and the fake embedder (the generation's recorded model in these tests)."""

import hashlib
import uuid
from typing import Any

import asyncpg
import pytest

from app.api.dependencies.search import get_search_deps
from app.domain.enums import IngestionState
from app.providers.search.postgres import PostgresSearchBackend
from app.services.search import SearchDeps
from tests.fakes import FakeEmbeddingProvider
from tests.test_indexing import POLICY
from tests.test_ingestion_ops import join_as
from tests.test_ingestion_stages import (  # noqa: F401 (pytest fixtures)
    World,
    admin,
    app,
    store,
    world,
)
from tests.test_search_backend import IdentifierChunker

pytestmark = pytest.mark.integration
S = IngestionState
TRAVEL = b"# Travel policy\n\nEconomy class for flights under six hours; business class beyond.\n"


def use_search(world: World, **settings: Any) -> None:
    configured = world.settings.model_copy(update=settings)
    world.app.dependency_overrides[get_search_deps] = lambda: SearchDeps(
        backend=PostgresSearchBackend(world.app.state.sessionmaker),
        embedder=FakeEmbeddingProvider(),
        settings=configured,
    )


async def ready(world: World, data: bytes, name: str) -> dict[str, Any]:
    job = await world.upload(data, name=name)
    assert await world.run(job, chunker=IdentifierChunker()) is S.READY
    return job


async def search(world: World, query: str, who: str = "alice", **body: Any) -> Any:
    return await world.api.post(
        f"/v1/knowledge-bases/{world.kb}/search",
        json={"query": query, **body},
        headers=world.h(who),
    )


async def test_search_returns_snippets_match_types_and_records_a_private_run(
    world: World, admin: asyncpg.Connection
) -> None:
    use_search(world)
    policy = await ready(world, POLICY, "parental-leave.md")

    response = await search(world, "  what is HR-142-B? ")

    assert response.status_code == 200, response.text
    body = response.json()
    top = body["hits"][0]
    assert top["document_id"] == policy["document_id"]
    assert "HR-142-B" in top["snippet"] or "«" in top["snippet"]
    assert top["match_type"] in {"exact", "both"}
    assert body["degraded"] is False
    assert body["debug"] is None

    run = await admin.fetchrow(
        "SELECT * FROM query_runs WHERE id = $1", uuid.UUID(body["query_run_id"])
    )
    assert run["query_text"] is None  # retention off: only the hash
    assert run["query_hash"] == hashlib.sha256(b"what is HR-142-B?").hexdigest()
    assert run["query_type"] == "search"
    assert run["knowledge_base_ids"] == [uuid.UUID(world.kb)]
    assert run["embedding_model"] == FakeEmbeddingProvider.model_id
    hits = await admin.fetchval(
        "SELECT count(*) FROM retrieval_hits WHERE query_run_id = $1", run["id"]
    )
    assert hits >= len(body["hits"])


async def test_query_text_is_kept_only_when_retention_allows(
    world: World, admin: asyncpg.Connection
) -> None:
    use_search(world, retain_query_text=True)
    await ready(world, POLICY, "parental-leave.md")

    body = (await search(world, "parental leave")).json()

    text = await admin.fetchval(
        "SELECT query_text FROM query_runs WHERE id = $1", uuid.UUID(body["query_run_id"])
    )
    assert text == "parental leave"


async def test_semantic_only_hits_get_their_leading_passage(world: World) -> None:
    use_search(world)
    await ready(world, POLICY, "parental-leave.md")

    # Words that appear only together with others, so full text (AND) misses but vectors match.
    body = (await search(world, "child arrival paid leave people team planned")).json()

    semantic = [h for h in body["hits"] if h["match_type"] == "semantic"]
    assert semantic
    assert all("«" not in h["snippet"] for h in semantic)


async def test_multi_kb_search_and_kb_access_errors(world: World) -> None:
    use_search(world)
    await ready(world, POLICY, "parental-leave.md")
    travel_kb = (
        await world.api.post("/v1/knowledge-bases", json={"name": "Travel"}, headers=world.h())
    ).json()["id"]
    travel = World(world.app, world.api, world.store, world.org, travel_kb)
    await ready(travel, TRAVEL, "travel.md")

    both = await world.api.post(
        "/v1/search",
        json={"query": "policy", "knowledge_base_ids": [world.kb, travel_kb]},
        headers=world.h(),
    )
    assert both.status_code == 200, both.text
    assert {h["knowledge_base_id"] for h in both.json()["hits"]} == {world.kb, travel_kb}

    unknown = await world.api.post(
        "/v1/search",
        json={"query": "policy", "knowledge_base_ids": [str(uuid.uuid4())]},
        headers=world.h(),
    )
    assert unknown.status_code == 404

    # Alice manages a KB restricted to someone else: she sees it exists but can't search it.
    await join_as(world, "bob", "member")
    bob = (await world.api.get("/v1/me", headers=world.h("bob"))).json()["user"]["id"]
    entries = [{"principal_type": "user", "principal_id": bob, "permission": "query"}]
    await world.api.put(
        f"/v1/knowledge-bases/{travel_kb}/permissions", json={"entries": entries}, headers=world.h()
    )
    await world.api.patch(
        f"/v1/knowledge-bases/{travel_kb}", json={"visibility": "restricted"}, headers=world.h()
    )
    forbidden = await travel.api.post(
        f"/v1/knowledge-bases/{travel_kb}/search", json={"query": "economy"}, headers=world.h()
    )
    assert forbidden.status_code == 403


async def test_a_kb_on_another_embedding_model_is_searched_lexically_and_reported(
    world: World, admin: asyncpg.Connection
) -> None:
    use_search(world)
    policy = await ready(world, POLICY, "parental-leave.md")
    travel_kb = (
        await world.api.post("/v1/knowledge-bases", json={"name": "Travel"}, headers=world.h())
    ).json()["id"]
    travel = World(world.app, world.api, world.store, world.org, travel_kb)
    await ready(travel, TRAVEL, "travel.md")
    await admin.execute(
        "UPDATE index_generations SET embedding_model = 'another/model' "
        "WHERE knowledge_base_id = $1",
        uuid.UUID(travel_kb),
    )

    response = await world.api.post(
        "/v1/search",
        json={"query": "economy flights", "knowledge_base_ids": [world.kb, travel_kb]},
        headers=world.h(),
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["degraded"] is True  # part of the request had no dense coverage
    by_kb = {
        kb: [h for h in body["hits"] if h["knowledge_base_id"] == kb]
        for kb in (world.kb, travel_kb)
    }
    assert any(h["match_type"] in {"semantic", "both"} for h in by_kb[world.kb])  # dense kept
    assert by_kb[travel_kb]
    assert all(h["match_type"] == "exact" for h in by_kb[travel_kb])
    assert policy["document_id"] in {h["document_id"] for h in by_kb[world.kb]}
    run = await admin.fetchrow(
        "SELECT degraded, embedding_model FROM query_runs WHERE id = $1",
        uuid.UUID(body["query_run_id"]),
    )
    assert run["degraded"] == ["dense_model_mismatch"]
    assert run["embedding_model"] == FakeEmbeddingProvider.model_id


async def test_filters_are_validated(world: World) -> None:
    use_search(world)
    await ready(world, POLICY, "parental-leave.md")

    unsupported = await search(world, "leave", filters={"department": "HR"})
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == "unsupported_filter"

    empty = await search(world, "​​ ")
    assert empty.status_code == 422


# --------------------------------------------------------------------------- debug & query runs


async def test_debug_needs_retrieval_debug_and_shows_branch_ranks(world: World) -> None:
    use_search(world)
    await join_as(world, "bob", "member")
    await ready(world, POLICY, "parental-leave.md")

    assert (await search(world, "parental leave", who="bob", debug=True)).status_code == 403

    debug = (await search(world, "parental leave weeks", debug=True)).json()["debug"]
    assert debug["embedding_model"] == FakeEmbeddingProvider.model_id
    assert debug["index_generation_ids"].keys() == {world.kb}
    assert debug["index_generation_id"] == debug["index_generation_ids"][world.kb]
    assert debug["principal_summary"].startswith("role owner")
    top = debug["hits"][0]
    assert top["fused_score"] is not None
    assert top["dense_rank"] is not None or top["lexical_rank"] is not None


async def test_query_runs_are_private_and_debug_never_shows_unreadable_documents(
    world: World,
) -> None:
    use_search(world)
    await join_as(world, "bob", "member")
    bob = (await world.api.get("/v1/me", headers=world.h("bob"))).json()["user"]["id"]
    alice = (await world.api.get("/v1/me", headers=world.h())).json()["user"]["id"]
    await ready(world, POLICY, "parental-leave.md")

    # A KB only Bob may read (Alice keeps manage rights through her role, not content access).
    secret_kb = (
        await world.api.post("/v1/knowledge-bases", json={"name": "Bob only"}, headers=world.h())
    ).json()["id"]
    secret = World(world.app, world.api, world.store, world.org, secret_kb)
    await ready(secret, TRAVEL, "bob-travel.md")
    entries = [{"principal_type": "user", "principal_id": bob, "permission": "query"}]
    await world.api.put(
        f"/v1/knowledge-bases/{secret_kb}/permissions", json={"entries": entries}, headers=world.h()
    )
    await world.api.patch(
        f"/v1/knowledge-bases/{secret_kb}", json={"visibility": "restricted"}, headers=world.h()
    )
    async with world.app.state.sessionmaker() as session, session.begin():
        from app.db.tenant import set_tenant_context
        from app.services.chunk_acl import sync_knowledge_base

        await set_tenant_context(session, uuid.UUID(world.org))
        await sync_knowledge_base(session, uuid.UUID(world.org), uuid.UUID(secret_kb))

    run = (
        await world.api.post(
            "/v1/search",
            json={"query": "economy flights policy", "knowledge_base_ids": [world.kb, secret_kb]},
            headers=world.h("bob"),
        )
    ).json()["query_run_id"]
    url = f"/v1/query-runs/{run}"

    mine = (await world.api.get(url, headers=world.h("bob"))).json()
    assert mine["debug"] is None  # Bob holds no retrieval.debug
    assert set(mine["knowledge_base_ids"]) == {world.kb, secret_kb}
    assert mine["knowledge_base_id"] is None

    audited = (await world.api.get(url, headers=world.h())).json()  # Alice: owner, debugger
    titles = {h["title"] for h in audited["debug"]["hits"]}
    assert "bob-travel" not in titles  # Alice can't read Bob's KB, so its hits stay hidden
    assert "hidden from you" in audited["debug"]["principal_summary"]
    assert alice not in audited["debug"]["principal_summary"]
