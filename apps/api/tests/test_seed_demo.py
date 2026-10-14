# ruff: noqa: F811  (fixtures imported from test_ingestion_stages)
"""The demo seed (`scripts/seed_demo.py`, S25) against the real API in-process: everything is
created through public endpoints, the restricted KB holds the HR-only document, and a second run
creates nothing new."""

import importlib.util
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import unquote, urlsplit

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import get_identity_verifier
from app.api.dependencies.storage import get_object_store
from app.core.config import Settings
from app.main import create_app
from app.providers.identity.base import VerifiedToken
from app.providers.storage import InMemoryObjectStore
from tests.fakes import FakeEmbeddingProvider, FakeIdentityVerifier
from tests.test_ingestion_stages import ISSUER, admin, store  # noqa: F401 (pytest fixtures)

pytestmark = pytest.mark.integration
SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "seed_demo.py"
PEOPLE = {
    "alice": "alice@acme.test",
    "bob": "bob@acme.test",
    "hana": "hana@acme.test",
    "carol": "carol@globex.test",
}


def seed_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("seed_demo", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["seed_demo"] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def demo_app(
    migrated_settings: Settings, admin: asyncpg.Connection, store: InMemoryObjectStore
) -> AsyncIterator[FastAPI]:
    settings = migrated_settings.model_copy(
        update={
            "malware_scanner": "none",
            "require_malware_scan": False,
            "embedding_provider": "sentence_transformers",
            "embedding_model": FakeEmbeddingProvider.model_id,
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


async def run_seed(app: FastAPI, store: InMemoryObjectStore) -> Any:
    module = seed_module()

    async def put_object(upload: dict[str, Any], data: bytes) -> None:
        url = urlsplit(upload["url"])  # memory://<bucket>/<key>
        await store.put(url.netloc, unquote(url.path.lstrip("/")), data, content_type="x")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        seeder = module.Seeder(client, lambda who: who, put_object=put_object, log=lambda _: None)
        await seeder.run()
        return seeder


async def test_the_seed_builds_the_demo_through_the_api_and_is_idempotent(
    demo_app: FastAPI, store: InMemoryObjectStore, admin: asyncpg.Connection
) -> None:
    first = await run_seed(demo_app, store)

    assert set(first.orgs) == {"acme", "globex"}
    assert len(first.jobs) == 16  # every manifest document uploaded once
    names = {
        (r["slug"], r["name"], r["visibility"])
        for r in await admin.fetch(
            "SELECT o.slug, kb.name, kb.visibility FROM knowledge_bases kb "
            "JOIN organizations o ON o.id = kb.organization_id"
        )
    }
    assert ("acme", "HR Confidential", "restricted") in names
    assert {("globex", "HR", "organization"), ("globex", "Support", "organization")} <= names
    rows = await admin.fetch(
        "SELECT u.email, r.key AS role FROM memberships m JOIN users u ON u.id = m.user_id "
        "JOIN roles r ON r.id = m.role_id JOIN organizations o ON o.id = m.organization_id "
        "WHERE o.slug = 'acme'"
    )
    roles = {r["email"]: r["role"] for r in rows}
    assert roles == {
        "alice@acme.test": "owner",
        "bob@acme.test": "member",
        "hana@acme.test": "knowledge_manager",
    }

    # The HR-only document sits in the restricted KB: Bob can't even see it, Hana (HR) can.
    confidential = first.kbs[("acme", "HR Confidential")]
    headers = {"X-Organization-Id": first.orgs["acme"]}
    async with AsyncClient(transport=ASGITransport(app=demo_app), base_url="http://test") as api:
        bob = await api.get(
            f"/v1/knowledge-bases/{confidential}",
            headers={**headers, "Authorization": "Bearer bob"},
        )
        hana = await api.get(
            f"/v1/knowledge-bases/{confidential}/documents",
            headers={**headers, "Authorization": "Bearer hana"},
        )
    assert bob.status_code == 404
    assert [d["title"] for d in hana.json()["items"]] == [
        "Acme Corp Compensation Bands 2026 (HR Only)"
    ]

    again = await run_seed(demo_app, store)
    assert again.jobs == {}  # nothing re-uploaded
    assert again.orgs == first.orgs
