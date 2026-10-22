# ruff: noqa: E501, F811  (fixtures imported from test_ingestion_stages; long SQL reads better unwrapped)
"""RAG profiles (S27, T5.3) and the debug search's RERANK/CONTEXT steps (Demo 3)."""

import uuid
from collections.abc import Sequence
from typing import Any

import asyncpg
import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.api.dependencies.search import get_search_deps
from app.api.errors import NotFound
from app.auth.authorization import RequestContext
from app.db.models import KnowledgeBase
from app.db.tenant import tenant_session
from app.domain.enums import IngestionState
from app.providers.rerankers.base import RerankerUnavailableError
from app.providers.rerankers.fake import FakeReranker
from app.providers.search.postgres import PostgresSearchBackend
from app.rag.orchestration.profiles import (
    RagProfileConfig,
    activate,
    active_profile,
    create_version,
)
from app.services.search import SearchDeps
from tests.fakes import FakeEmbeddingProvider
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
HANDBOOK = (
    b"# Parental leave\n\nEmployees receive sixteen weeks of paid parental leave (HR-142-B).\n\n"
    b"Requests go to the people team thirty days before the leave starts.\n\n"
    b"# Travel\n\nEconomy class applies to flights shorter than six hours.\n"
)


class BrokenReranker(FakeReranker):
    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        raise RerankerUnavailableError("model not loaded")


def use(world: World, reranker: Any) -> None:
    world.app.dependency_overrides[get_search_deps] = lambda: SearchDeps(
        backend=PostgresSearchBackend(world.app.state.sessionmaker),
        embedder=FakeEmbeddingProvider(),
        settings=world.settings,
        reranker=reranker,
        count_tokens=lambda value: len(value.split()),
    )


async def owner_context(world: World) -> RequestContext:
    me = (await world.api.get("/v1/me", headers=world.h())).json()
    from app.auth.permissions import SYSTEM_ROLE_PERMISSIONS, SystemRole

    return RequestContext(
        user_id=uuid.UUID(me["user"]["id"]),
        organization_id=uuid.UUID(world.org),
        role="owner",
        permissions=SYSTEM_ROLE_PERMISSIONS[SystemRole.OWNER],
        group_ids=frozenset(),
    )


async def debug_search(world: World, query: str) -> Any:
    response = await world.api.post(
        f"/v1/knowledge-bases/{world.kb}/search",
        json={"query": query, "debug": True},
        headers=world.h(),
    )
    return response


# --------------------------------------------------------------------------- profiles


async def test_kbs_use_the_system_default_until_activated_and_versions_never_change(
    world: World,
) -> None:
    org = uuid.UUID(world.org)
    ctx = await owner_context(world)
    async with tenant_session(world.app.state.sessionmaker, org) as session:
        kb = await session.get(KnowledgeBase, uuid.UUID(world.kb))
        assert kb is not None
        default = await active_profile(session, kb)
        assert default.label == "default-hybrid-v1"
        assert (default.config.dense_k, default.config.final_context_k) == (50, 8)

        first = await create_version(session, ctx, "tight", RagProfileConfig(final_context_k=4))
        second = await create_version(session, ctx, "tight", RagProfileConfig(final_context_k=3))
        assert (first.version, second.version) == (1, 2)
        await activate(session, ctx, kb, second.id)
        assert (await active_profile(session, kb)).label == "tight-v2"

    # The runtime role may only insert versions: updates and deletes are refused by Postgres.
    for statement in (
        "UPDATE rag_profiles SET config_json = '{}'::jsonb",
        "DELETE FROM rag_profiles",
    ):
        with pytest.raises(ProgrammingError, match="permission denied"):
            async with tenant_session(world.app.state.sessionmaker, org) as session:
                await session.execute(text(statement))


async def test_another_organizations_profile_cant_be_activated(
    world: World, admin: asyncpg.Connection
) -> None:
    other_org, foreign = uuid.uuid4(), uuid.uuid4()
    await admin.execute(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Other', $2)",
        other_org,
        f"o-{uuid.uuid4().hex[:6]}",
    )
    await admin.execute(
        "INSERT INTO rag_profiles (id, organization_id, name, version, config_json) VALUES ($1, $2, 'theirs', 1, '{}')",
        foreign, other_org,
    )  # fmt: skip
    ctx = await owner_context(world)
    async with tenant_session(world.app.state.sessionmaker, uuid.UUID(world.org)) as session:
        kb = await session.get(KnowledgeBase, uuid.UUID(world.kb))
        assert kb is not None
        with pytest.raises(NotFound):
            await activate(session, ctx, kb, foreign)


# --------------------------------------------------------------------------- debug RERANK / CONTEXT


async def test_debug_search_reranks_and_shows_the_selected_context(
    world: World, admin: asyncpg.Connection
) -> None:
    use(world, FakeReranker())
    job = await world.upload(HANDBOOK)
    assert await world.run(job, chunker=IdentifierChunker()) is S.READY

    body = (await debug_search(world, "parental leave weeks")).json()

    debug = body["debug"]
    assert debug["rag_profile_version"] == "default-hybrid-v1"
    assert debug["reranker_model"] == FakeReranker.model_id
    assert "rerank_bypassed" not in debug["degraded"]
    scored = [h for h in debug["hits"] if h["rerank_score"] is not None]
    assert scored
    selected = [h for h in debug["hits"] if h["selected_for_context"]]
    assert selected
    top = max(scored, key=lambda h: h["rerank_score"])
    assert top["selected_for_context"]
    run = await admin.fetchrow(
        "SELECT rag_profile_version, reranker_model, rerank_latency_ms FROM query_runs WHERE id = $1",
        uuid.UUID(body["query_run_id"]),
    )
    assert run["rag_profile_version"] == "default-hybrid-v1"
    assert run["rerank_latency_ms"] is not None


async def test_a_failing_reranker_degrades_to_the_fused_order(world: World) -> None:
    use(world, BrokenReranker())
    job = await world.upload(HANDBOOK)
    assert await world.run(job, chunker=IdentifierChunker()) is S.READY

    body = (await debug_search(world, "parental leave weeks")).json()

    assert "rerank_bypassed" in body["debug"]["degraded"]
    assert body["degraded"] is True
    assert body["debug"]["reranker_model"] is None
    assert any(h["selected_for_context"] for h in body["debug"]["hits"])  # fused order packed


async def test_a_profile_that_forbids_degradation_fails_instead(world: World) -> None:
    use(world, None)
    job = await world.upload(HANDBOOK)
    assert await world.run(job, chunker=IdentifierChunker()) is S.READY
    ctx = await owner_context(world)
    async with tenant_session(world.app.state.sessionmaker, uuid.UUID(world.org)) as session:
        kb = await session.get(KnowledgeBase, uuid.UUID(world.kb))
        assert kb is not None
        strict = await create_version(
            session, ctx, "strict", RagProfileConfig(allow_degraded_rerank=False)
        )
        await activate(session, ctx, kb, strict.id)

    response = await debug_search(world, "parental leave weeks")

    assert response.status_code == 503
    plain = await world.api.post(
        f"/v1/knowledge-bases/{world.kb}/search",
        json={"query": "parental leave"},
        headers=world.h(),
    )
    assert plain.status_code == 200  # plain search never reranks
