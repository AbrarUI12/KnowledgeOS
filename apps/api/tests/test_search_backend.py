# ruff: noqa: E501, F811  (fixtures imported from test_ingestion_stages; long SQL reads better unwrapped)
"""Permission-aware hybrid search (T4.4, S24) against real PostgreSQL + pgvector.

The corpus goes through the real ingestion pipeline (fake parser/chunker/embedder), so every chunk
carries the ACL tokens, full text and vectors indexing really writes. Then it is made hostile:
a superseded version, an archived document, a retired index generation and a restricted KB.
"""

import asyncio
import hashlib
import re
import uuid
from dataclasses import dataclass
from typing import Any

import asyncpg
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.db.session import create_engine, create_sessionmaker
from app.db.tenant import tenant_session
from app.domain.enums import IngestionState
from app.ingestion.canonical import CanonicalDocument
from app.ingestion.chunking.types import ChunkDraft
from app.providers.search.base import HybridSearchRequest, QueryFilters, SearchScope
from app.providers.search.postgres import PostgresSearchBackend, UnsupportedFilter
from app.services.chunk_acl import sync_knowledge_base
from tests.fakes import FakeChunker, FakeEmbeddingProvider
from tests.test_ingestion_ops import join_as, upload_version
from tests.test_ingestion_stages import (  # noqa: F401 (pytest fixtures)
    World,
    admin,
    app,
    store,
    world,
)

pytestmark = pytest.mark.integration
S = IngestionState
MODEL = FakeEmbeddingProvider.model_id
POLICY_V1 = b"# Parental leave\n\nEmployees receive sixteen weeks of paid parental leave.\n"
POLICY_V2 = (
    b"# Parental leave\n\nEmployees receive eighteen weeks of paid parental leave under HR-142-B.\n\n"
    b"Requests go to the people team thirty days ahead.\n"
)
TRAVEL = b"# Travel\n\nEconomy class for flights under six hours.\n"
COMPENSATION = b"# Compensation bands\n\nSalary band L4 ranges from 90k to 120k (COMP-7).\n"


class IdentifierChunker(FakeChunker):
    """The fake chunker plus T3.4's identifier extraction."""

    def chunk(self, document: CanonicalDocument) -> list[ChunkDraft]:
        return [
            draft.model_copy(
                update={
                    "identifiers": re.findall(
                        r"\b[A-Z]{2,}(?:-\d+)+(?:-[A-Z0-9]+)*\b", draft.content
                    )
                }
            )
            for draft in super().chunk(document)
        ]


@dataclass
class Corpus:
    world: World
    org: uuid.UUID
    hr_kb: uuid.UUID
    comp_kb: uuid.UUID
    alice: tuple[str, ...]
    bob: tuple[str, ...]
    policy: dict[str, Any]  # active version (v2) upload
    superseded: set[uuid.UUID]  # v1 chunks
    archived: set[uuid.UUID]
    retired: set[uuid.UUID]
    restricted: set[uuid.UUID]
    rows: list[asyncpg.Record]  # every chunk with what the predicate needs (brute force)

    def scope(
        self, tokens: tuple[str, ...], kbs: tuple[uuid.UUID, ...] | None = None
    ) -> SearchScope:
        return SearchScope(
            organization_id=self.org,
            knowledge_base_ids=kbs or (self.hr_kb, self.comp_kb),
            principal_tokens=tokens,
        )


async def request(
    corpus: Corpus, tokens: tuple[str, ...], query: str, **overrides: Any
) -> HybridSearchRequest:
    embedding = await FakeEmbeddingProvider().embed_query(query)
    values: dict[str, Any] = {
        "scope": corpus.scope(tokens),
        "query": query,
        "query_embedding": tuple(embedding),
        "embedding_model": MODEL,
        "dense_k": 20,
        "lexical_k": 20,
        **overrides,
    }
    return HybridSearchRequest(**values)


def ids(hits: Any) -> set[uuid.UUID]:
    return {hit.chunk_id for hit in hits}


async def chunk_ids(admin: asyncpg.Connection, version_id: str) -> set[uuid.UUID]:
    return {
        r["id"]
        for r in await admin.fetch(
            "SELECT id FROM chunks WHERE document_version_id = $1", uuid.UUID(version_id)
        )
    }


@pytest.fixture
async def corpus(world: World, admin: asyncpg.Connection) -> Corpus:
    await join_as(world, "bob", "member")
    me = {
        who: (await world.api.get("/v1/me", headers=world.h(who))).json()["user"]["id"]
        for who in ("alice", "bob")
    }
    hr_group = (
        await world.api.post(
            f"/v1/organizations/{world.org}/groups", json={"name": "HR"}, headers=world.h()
        )
    ).json()["id"]
    await world.api.post(
        f"/v1/organizations/{world.org}/groups/{hr_group}/members",
        json={"user_id": me["alice"]},
        headers=world.h(),
    )
    chunker = IdentifierChunker()

    # Organization-wide HR KB: a superseded version and an archived document.
    v1 = await world.upload(POLICY_V1, name="Parental leave policy.md")
    assert await world.run(v1, chunker=chunker) is S.READY
    v2 = await upload_version(world, v1["document_id"], POLICY_V2)
    assert await world.run(v2, chunker=chunker) is S.READY
    travel = await world.upload(TRAVEL, name="Travel policy.md")
    assert await world.run(travel, chunker=chunker) is S.READY
    assert (
        await world.api.delete(f"/v1/documents/{travel['document_id']}", headers=world.h())
    ).status_code == 204

    # Restricted compensation KB: HR group only.
    comp_kb = (
        await world.api.post(
            "/v1/knowledge-bases",
            json={"name": "Compensation", "visibility": "restricted"},
            headers=world.h(),
        )
    ).json()["id"]
    entries = [
        {"principal_type": "user", "principal_id": me["alice"], "permission": "manage"},
        {"principal_type": "group", "principal_id": hr_group, "permission": "query"},
    ]
    await world.api.put(
        f"/v1/knowledge-bases/{comp_kb}/permissions", json={"entries": entries}, headers=world.h()
    )
    comp = World(world.app, world.api, world.store, world.org, comp_kb)
    bands = await comp.upload(COMPENSATION, name="Compensation bands 2026.md")
    assert await comp.run(bands, chunker=chunker) is S.READY

    # A retired generation of the HR KB holding copies of the active chunks.
    retired_generation = uuid.uuid4()
    await admin.execute(
        "INSERT INTO index_generations (id, organization_id, knowledge_base_id, generation_number, status, "
        "embedding_provider, embedding_model, embedding_dimension, chunker_name) "
        "VALUES ($1, $2, $3, 2, 'retired', 'fake', $4, 1024, 'fake')",
        retired_generation, uuid.UUID(world.org), uuid.UUID(world.kb), MODEL,
    )  # fmt: skip
    await admin.execute(
        "INSERT INTO chunks (id, organization_id, knowledge_base_id, document_id, document_version_id, "
        "index_generation_id, ordinal, block_type, section_path, block_ids, content, embedding_text, "
        "content_hash, token_count, embedding, search_vector, fts_config, identifiers, access_principals) "
        "SELECT gen_random_uuid(), organization_id, knowledge_base_id, document_id, document_version_id, $1, "
        "ordinal, block_type, section_path, block_ids, content, embedding_text, content_hash, token_count, "
        "embedding, search_vector, fts_config, identifiers, access_principals "
        "FROM chunks WHERE document_version_id = $2",
        retired_generation, uuid.UUID(v2["document_version_id"]),
    )  # fmt: skip

    rows = await admin.fetch(
        "SELECT c.id, c.organization_id, c.knowledge_base_id, c.is_parent, c.visibility, c.access_principals, c.document_principals, "
        "c.index_generation_id = kb.active_index_generation_id AS active_generation, "
        "c.document_version_id = d.active_version_id AS active_version, "
        "d.status = 'active' AND d.archived_at IS NULL AND kb.archived_at IS NULL AS live "
        "FROM chunks c JOIN documents d ON d.id = c.document_id JOIN knowledge_bases kb ON kb.id = c.knowledge_base_id"
    )
    org = world.org
    return Corpus(
        world=world,
        org=uuid.UUID(org),
        hr_kb=uuid.UUID(world.kb),
        comp_kb=uuid.UUID(comp_kb),
        alice=(f"user:{me['alice']}", "role:owner", f"org:{org}", f"group:{hr_group}"),
        bob=(f"user:{me['bob']}", "role:member", f"org:{org}"),
        policy=v2,
        superseded=await chunk_ids(admin, v1["document_version_id"]),
        archived=await chunk_ids(admin, travel["document_version_id"]),
        retired={
            r["id"]
            for r in await admin.fetch(
                "SELECT id FROM chunks WHERE index_generation_id = $1", retired_generation
            )
        },
        restricted=await chunk_ids(admin, bands["document_version_id"]),
        rows=rows,
    )


def backend(corpus: Corpus) -> PostgresSearchBackend:
    return PostgresSearchBackend(corpus.world.app.state.sessionmaker)


# --------------------------------------------------------------------------- authorization


@pytest.mark.parametrize(
    "query", ["Compensation bands 2026", "Compensaton bnds", "salary band L4 COMP-7"]
)
async def test_restricted_chunks_never_reach_outsiders_even_for_exact_titles(
    corpus: Corpus, query: str
) -> None:
    for_bob = await backend(corpus).hybrid_search(await request(corpus, corpus.bob, query))
    assert not (ids(for_bob.dense) | ids(for_bob.lexical)) & corpus.restricted

    for_alice = await backend(corpus).hybrid_search(await request(corpus, corpus.alice, query))
    assert corpus.restricted & ids(for_alice.lexical)  # the same query does find it for HR


async def test_superseded_archived_and_retired_chunks_never_appear(corpus: Corpus) -> None:
    hidden = corpus.superseded | corpus.archived | corpus.retired
    for query in ("parental leave weeks", "sixteen weeks", "economy flights travel"):
        result = await backend(corpus).hybrid_search(await request(corpus, corpus.alice, query))
        assert not (ids(result.dense) | ids(result.lexical)) & hidden
    current = await backend(corpus).hybrid_search(
        await request(corpus, corpus.alice, "parental leave weeks")
    )
    assert {h.candidate.document_version_id for h in current.lexical} == {
        uuid.UUID(corpus.policy["document_version_id"])
    }
    assert current.index_generation_ids.keys() == {corpus.hr_kb, corpus.comp_kb}


@settings(
    max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    tokens=st.sets(
        st.sampled_from(
            ["role:owner", "role:member", "role:viewer", "user:nobody", "org:elsewhere"]
        ),
        max_size=3,
    ),
    who=st.sampled_from(["alice", "bob", "none"]),
    kbs=st.sampled_from(["hr", "comp", "both"]),
    query=st.sampled_from(
        [
            "parental leave",
            "salary band",
            "Compensation bands 2026",
            "travel economy",
            "HR-142-B",
            "weeks",
        ]
    ),
)
def test_every_returned_chunk_satisfies_the_predicate(
    corpus: Corpus, tokens: set[str], who: str, kbs: str, query: str
) -> None:
    """Brute force: whatever the principals, KBs and query, every hit passes the Python predicate."""
    caller = {"alice": corpus.alice, "bob": corpus.bob, "none": ()}[who]
    principals = tuple(sorted({*caller, *tokens} or {"user:nobody"}))
    scope_kbs = {
        "hr": (corpus.hr_kb,),
        "comp": (corpus.comp_kb,),
        "both": (corpus.hr_kb, corpus.comp_kb),
    }[kbs]
    allowed = {
        r["id"]
        for r in corpus.rows
        if r["organization_id"] == corpus.org
        and r["knowledge_base_id"] in scope_kbs
        and r["active_generation"]
        and r["active_version"]
        and r["live"]
        and not r["is_parent"]
        and r["visibility"] == "visible"
        and set(r["access_principals"]) & set(principals)
        and (not r["document_principals"] or set(r["document_principals"]) & set(principals))
    }

    async def search() -> set[uuid.UUID]:
        engine = create_engine(corpus.world.settings)
        try:
            found = await PostgresSearchBackend(create_sessionmaker(engine)).hybrid_search(
                await request(corpus, principals, query, scope=corpus.scope(principals, scope_kbs))
            )
            return ids(found.dense) | ids(found.lexical)
        finally:
            await engine.dispose()

    assert asyncio.run(search()) <= allowed


# --------------------------------------------------------------------------- ranking features


async def test_exact_identifiers_are_boosted_case_insensitively(corpus: Corpus) -> None:
    result = await backend(corpus).hybrid_search(
        await request(corpus, corpus.bob, "what is hr-142-b?")
    )

    top = result.lexical[0]
    assert "HR-142-B" in top.candidate.content
    assert top.lexical_score is not None
    assert top.lexical_score >= 1.0


async def test_misspelled_titles_fall_back_to_trigram_similarity(corpus: Corpus) -> None:
    result = await backend(corpus).lexical_search(
        await request(corpus, corpus.bob, "Parentl leeve polcy")
    )

    assert result
    assert {h.candidate.title for h in result} == {"Parental leave policy"}


async def test_dense_only_compares_vectors_of_the_same_model(corpus: Corpus) -> None:
    other = await request(
        corpus, corpus.alice, "parental leave", embedding_model="some-other-model"
    )

    result = await backend(corpus).hybrid_search(other)

    assert result.dense == []
    assert result.lexical  # the text branch is unaffected


async def test_filters_narrow_and_unsupported_ones_are_refused(corpus: Corpus) -> None:
    document = uuid.UUID(corpus.policy["document_id"])
    only = QueryFilters(document_ids=(document,))
    narrowed = await backend(corpus).hybrid_search(
        await request(corpus, corpus.alice, "band leave weeks", filters=only)
    )
    assert {h.candidate.document_id for h in narrowed.dense + narrowed.lexical} == {document}

    spanish = await backend(corpus).hybrid_search(
        await request(
            corpus, corpus.alice, "parental leave", filters=QueryFilters(languages=("es",))
        )
    )
    assert spanish.dense == []
    assert spanish.lexical == []

    with pytest.raises(UnsupportedFilter):
        await backend(corpus).hybrid_search(
            await request(corpus, corpus.alice, "leave", filters=QueryFilters(department="HR"))
        )


async def test_one_failed_branch_degrades_only_when_allowed(
    corpus: Corpus, monkeypatch: pytest.MonkeyPatch
) -> None:
    search = backend(corpus)

    async def broken(session: Any, request: HybridSearchRequest) -> Any:
        raise RuntimeError("vector index unavailable")

    monkeypatch.setattr(search, "_dense", broken)
    degraded = await search.hybrid_search(await request(corpus, corpus.alice, "parental leave"))
    assert degraded.degraded.dense_unavailable
    assert not degraded.degraded.lexical_unavailable
    assert degraded.dense == []
    assert degraded.lexical
    assert degraded.timing.dense_ms is None
    assert degraded.timing.lexical_ms is not None

    with pytest.raises(RuntimeError, match="vector index unavailable"):
        await search.hybrid_search(
            await request(corpus, corpus.alice, "parental leave", allow_degraded=False)
        )


async def test_neighbors_are_adjacent_authorized_chunks(
    corpus: Corpus, admin: asyncpg.Connection
) -> None:
    first, second = [
        r["id"]
        for r in await admin.fetch(
            "SELECT id FROM chunks WHERE document_version_id = $1 AND index_generation_id = "
            "(SELECT active_index_generation_id FROM knowledge_bases WHERE id = $2) ORDER BY ordinal",
            uuid.UUID(corpus.policy["document_version_id"]),
            corpus.hr_kb,
        )
    ]
    scope = corpus.scope(corpus.alice)

    assert ids(await backend(corpus).neighbors(scope, first, before=1, after=1)) == {second}
    assert ids(await backend(corpus).neighbors(scope, second, before=1, after=0)) == {first}
    restricted = next(iter(corpus.restricted))
    assert await backend(corpus).neighbors(corpus.scope(corpus.bob), restricted) == []


async def test_a_document_acl_narrows_search_results(
    corpus: Corpus, admin: asyncpg.Connection
) -> None:
    """KB access alone isn't enough when the document has its own ACL (T4.2 two-token model)."""
    hr_group = corpus.alice[-1].removeprefix("group:")
    await admin.execute(
        "INSERT INTO document_acl (organization_id, document_id, principal_type, principal_id, permission) "
        "VALUES ($1, $2, 'group', $3, 'query')",
        corpus.org, uuid.UUID(corpus.policy["document_id"]), hr_group,
    )  # fmt: skip
    async with tenant_session(corpus.world.app.state.sessionmaker, corpus.org) as session:
        await sync_knowledge_base(session, corpus.org, corpus.hr_kb)
    policy = uuid.UUID(corpus.policy["document_id"])

    for_bob = await backend(corpus).hybrid_search(
        await request(corpus, corpus.bob, "parental leave weeks")
    )
    for_alice = await backend(corpus).hybrid_search(
        await request(corpus, corpus.alice, "parental leave weeks")
    )

    assert policy not in {h.candidate.document_id for h in for_bob.dense + for_bob.lexical}
    assert policy in {h.candidate.document_id for h in for_alice.lexical}


class SectionChunker(FakeChunker):
    """Pairs of fake children under one parent each: P0 c1 c2 | P3 c4 c5 (S19 parent/child)."""

    def chunk(self, document: CanonicalDocument) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        children = super().chunk(document)
        for start in range(0, len(children), 2):
            pair = children[start : start + 2]
            parent_ordinal = len(drafts)
            text = "\n\n".join(c.content for c in pair)
            drafts.append(
                pair[0].model_copy(
                    update={
                        "ordinal": parent_ordinal,
                        "is_parent": True,
                        "content": text,
                        "embedding_text": text,
                        "content_hash": hashlib.sha256(text.encode()).hexdigest(),
                    }
                )
            )
            drafts += [
                c.model_copy(update={"ordinal": len(drafts) + i, "parent_ordinal": parent_ordinal})
                for i, c in enumerate(pair)
            ]
        return drafts


async def test_neighbors_stay_inside_the_parent_section(
    corpus: Corpus, admin: asyncpg.Connection
) -> None:
    """Expansion never crosses a section: the packer requires ±1 neighbors (T5.1)."""
    text = b"# Sections\n\nAlpha one.\n\nAlpha two.\n\nBeta one.\n\nBeta two.\n"
    job = await corpus.world.upload(text, name="sections.md")
    assert await corpus.world.run(job, chunker=SectionChunker()) is S.READY
    children = [
        r["id"]
        for r in await admin.fetch(
            "SELECT id FROM chunks WHERE document_version_id = $1 AND NOT is_parent ORDER BY ordinal",
            uuid.UUID(job["document_version_id"]),
        )
    ]
    alpha_one, alpha_two, beta_one, _ = children
    scope = corpus.scope(corpus.alice)

    assert ids(await backend(corpus).neighbors(scope, alpha_one, after=1)) == {alpha_two}
    assert await backend(corpus).neighbors(scope, alpha_two, before=0, after=1) == []
    assert await backend(corpus).neighbors(scope, beta_one, before=1, after=0) == []
