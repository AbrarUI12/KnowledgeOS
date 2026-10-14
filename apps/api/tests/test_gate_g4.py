# ruff: noqa: E501, F811  (fixtures imported from other test modules; long SQL reads better unwrapped)
"""Gate G4 (session.md §6, S26): retrieval over the full demo corpus with the real libraries.

Seeds the demo through the API (`scripts/seed_demo.py`), ingests every document with the real
parsers (Docling, Office), normalization and the real Qwen3 embedder, then checks the G4
checklist through the search API:
- an exact identifier (`HR-142-B`) is in the top 3;
- a paraphrased question (Demo 1) finds the 2026 handbook in the top 5;
- restricted chunks never reach Bob (Demo 5), but Hana finds them;
- junk in a non-active (candidate) generation never appears;
- Carol (Globex) can't reach Acme at all (Demo 6).

Opt-in (`KOS_GATE=1`, `make gate-g4`): Docling and the embedding model make it take minutes.
Content scanning and chunking use the contract fakes until T3.4's libraries merge.
"""

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import get_identity_verifier
from app.api.dependencies.search import get_search_deps
from app.api.dependencies.storage import get_object_store
from app.core.config import Settings
from app.db.types import vector_literal
from app.domain.enums import IngestionState
from app.ingestion.normalize import normalize
from app.ingestion.parsing.docling import DoclingParser
from app.ingestion.parsing.office import OfficeParser
from app.ingestion.runner import run_job
from app.ingestion.stages import STUB_STAGES
from app.ingestion.stages.pipeline import StageDeps, build_stages
from app.main import create_app
from app.providers.embeddings.sentence_transformers import SentenceTransformersEmbeddingProvider
from app.providers.identity.base import VerifiedToken
from app.providers.search.postgres import PostgresSearchBackend
from app.providers.storage import InMemoryObjectStore
from app.services.search import SearchDeps
from tests.fakes import FakeContentScanner, FakeIdentityVerifier, FakeMalwareScanner
from tests.test_ingestion_stages import ISSUER, admin, store  # noqa: F401 (pytest fixtures)
from tests.test_search_backend import IdentifierChunker
from tests.test_seed_demo import PEOPLE, run_seed, seed_module

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
    pytest.mark.gate,
    pytest.mark.skipif(os.environ.get("KOS_GATE") != "1", reason="set KOS_GATE=1 (make gate-g4)"),
]
MODEL = "Qwen/Qwen3-Embedding-0.6B"
ASSETS = Path(__file__).resolve().parents[1] / ".venv" / "docling-assets"
S = IngestionState


@pytest.fixture
async def gate_app(
    migrated_settings: Settings, admin: asyncpg.Connection, store: InMemoryObjectStore
) -> AsyncIterator[FastAPI]:
    settings = migrated_settings.model_copy(
        update={
            "malware_scanner": "none",
            "require_malware_scan": False,
            "embedding_provider": "sentence_transformers",
            "embedding_model": MODEL,
        }
    )
    application = create_app(settings)
    tokens = {
        who: VerifiedToken(
            issuer=ISSUER, subject=f"{who}-sub", email=email, claims={"email_verified": True}
        )
        for who, email in PEOPLE.items()
    }
    application.dependency_overrides[get_identity_verifier] = lambda: FakeIdentityVerifier(tokens)
    application.dependency_overrides[get_object_store] = lambda: store
    async with application.router.lifespan_context(application):
        yield application


async def ingest(app: FastAPI, store: InMemoryObjectStore, seeder: Any, embedder: Any) -> None:
    org_of = {
        entry["title"]: seeder.orgs[entry["org"]]
        for entry in seed_module().manifest()
        if entry["title"] in seeder.jobs
    }
    deps = StageDeps(
        settings=app.state.settings,
        store=store,
        malware_scanner=FakeMalwareScanner(),
        parsers=(
            DoclingParser(artifacts_path=ASSETS if ASSETS.exists() else None, ocr=False),
            OfficeParser(),
        ),
        normalize=normalize,
        content_scanner=FakeContentScanner(),
        chunker=IdentifierChunker(),
        embedder=embedder,
    )
    stages = build_stages(deps, STUB_STAGES)
    states = {}
    for title, job in seeder.jobs.items():
        states[title] = await run_job(
            app.state.sessionmaker,
            organization_id=uuid.UUID(org_of[title]),
            job_id=uuid.UUID(job),
            worker_id="gate-g4",
            stages=stages,
        )
    poisoned = {t for t, s in states.items() if s is S.PENDING_APPROVAL}
    assert len(poisoned) == 1  # the poisoned engineering note is held for approval
    assert all(s is S.READY for t, s in states.items() if t not in poisoned), states


async def test_gate_g4(
    gate_app: FastAPI, store: InMemoryObjectStore, admin: asyncpg.Connection
) -> None:
    embedder = SentenceTransformersEmbeddingProvider(device="cpu", max_seq_length=512)
    seeder = await run_seed(gate_app, store)
    await ingest(gate_app, store, seeder, embedder)
    gate_app.dependency_overrides[get_search_deps] = lambda: SearchDeps(
        backend=PostgresSearchBackend(gate_app.state.sessionmaker),
        embedder=embedder,
        settings=gate_app.state.settings,
    )
    acme, globex = seeder.orgs["acme"], seeder.orgs["globex"]
    hr = seeder.kbs[("acme", "HR")]
    confidential = seeder.kbs[("acme", "HR Confidential")]
    acme_kbs = [
        kb
        for (slug, name), kb in seeder.kbs.items()
        if slug == "acme" and name != "HR Confidential"
    ]
    globex_kbs = [kb for (slug, _), kb in seeder.kbs.items() if slug == "globex"]

    # Junk in a non-active generation of the HR KB, made to look like the perfect match.
    query_vector = await embedder.embed_query("HR-142-B parental leave weeks")
    candidate, junk = uuid.uuid4(), uuid.uuid4()
    document, version = await admin.fetchrow(
        "SELECT d.id, d.active_version_id FROM documents d WHERE d.knowledge_base_id = $1 LIMIT 1",
        uuid.UUID(hr),
    )
    await admin.execute(
        "INSERT INTO index_generations (id, organization_id, knowledge_base_id, generation_number, "
        "status, embedding_provider, embedding_model, embedding_dimension, chunker_name) "
        "VALUES ($1, $2, $3, 2, 'candidate', 'sentence_transformers', $4, 1024, 'junk')",
        candidate, uuid.UUID(acme), uuid.UUID(hr), MODEL,
    )  # fmt: skip
    await admin.execute(
        "INSERT INTO chunks (id, organization_id, knowledge_base_id, document_id, document_version_id, "
        "index_generation_id, ordinal, block_type, content, embedding_text, content_hash, token_count, "
        "embedding, search_vector, fts_config, identifiers, access_principals) "
        "VALUES ($1, $2, $3, $4, $5, $6, 0, 'paragraph', $7, $7, repeat('0', 64), 9, $8::vector, "
        "to_tsvector('english', $7), 'english', ARRAY['HR-142-B'], ARRAY[$9])",
        junk, uuid.UUID(acme), uuid.UUID(hr), document, version, candidate,
        "JUNK HR-142-B parental leave weeks", vector_literal(query_vector), f"org:{acme}",
    )  # fmt: skip

    async with AsyncClient(transport=ASGITransport(app=gate_app), base_url="http://test") as api:

        async def search(who: str, org: str, kbs: list[str], query: str) -> Any:
            response = await api.post(
                "/v1/search",
                json={"query": query, "knowledge_base_ids": kbs, "limit": 10},
                headers={"Authorization": f"Bearer {who}", "X-Organization-Id": org},
            )
            assert response.status_code == 200, response.text
            return response.json()["hits"]

        # 1. Exact identifier in the top 3 (Demo 2).
        exact = await search("bob", acme, acme_kbs, "HR-142-B")
        plain = [h["snippet"].replace("«", "").replace("»", "") for h in exact[:3]]
        assert any("HR-142-B" in snippet for snippet in plain), plain
        assert all(h["chunk_id"] != str(junk) for h in exact)  # 4. never the candidate generation

        # 2. A paraphrase finds the 2026 handbook in the top 5 (Demo 1).
        paraphrase = await search(
            "bob", acme, acme_kbs, "How long can new parents stay home with pay?"
        )
        assert "Acme Corp Employee Handbook 2026" in {h["title"] for h in paraphrase[:5]}, (
            paraphrase[:5]
        )

        # 3. Restricted chunks: Bob can't reach them even by exact title (Demo 5); Hana can.
        title = "Acme Corp Compensation Bands 2026 (HR Only)"
        bob_view = await search("bob", acme, acme_kbs, title)
        assert all(h["knowledge_base_id"] != confidential for h in bob_view)
        blocked = await api.post(
            "/v1/search",
            json={"query": title, "knowledge_base_ids": [confidential]},
            headers={"Authorization": "Bearer bob", "X-Organization-Id": acme},
        )
        assert blocked.status_code == 404
        hana_view = await search("hana", acme, [confidential], title)
        assert hana_view
        assert hana_view[0]["title"] == title

        # 5. Carol (Globex) searching an Acme phrase gets only Globex content (Demo 6).
        carol_view = await search("carol", globex, globex_kbs, "Acme Corp Employee Handbook 2026")
        assert {h["knowledge_base_id"] for h in carol_view} <= set(globex_kbs)
        cross = await api.post(
            "/v1/search",
            json={"query": "parental leave", "knowledge_base_ids": [hr]},
            headers={"Authorization": "Bearer carol", "X-Organization-Id": globex},
        )
        assert cross.status_code == 404
