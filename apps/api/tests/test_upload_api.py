"""Secure upload flow and document APIs against real PostgreSQL + MinIO (T2.4, S13)."""

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import get_identity_verifier
from app.core.config import Settings
from app.main import create_app
from app.providers.identity.base import VerifiedToken
from tests.fakes import FakeIdentityVerifier

pytestmark = pytest.mark.integration

ISSUER = "https://idp.test/realms/knowledgeos"
CONTENT = b"Parental leave: 16 weeks (policy HR-142-B).\n" * 20


@pytest.fixture
async def admin(admin_dsn: str, migrated_settings: Settings) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(admin_dsn)
    try:
        yield conn
    finally:
        async with conn.transaction():
            await conn.execute("SET LOCAL app.audit_purge = 'on'")
            await conn.execute("DELETE FROM audit_events")
            await conn.execute("DELETE FROM organizations")
            await conn.execute("DELETE FROM users")
        await conn.close()


@pytest.fixture
async def app(migrated_settings: Settings, admin: asyncpg.Connection) -> AsyncIterator[FastAPI]:
    application = create_app(migrated_settings)
    tokens = {
        n: VerifiedToken(
            issuer=ISSUER,
            subject=f"{n}-sub",
            email=f"{n}@acme.test",
            claims={"email_verified": True},
        )
        for n in ("alice", "bob", "carol")
    }
    application.dependency_overrides[get_identity_verifier] = lambda: FakeIdentityVerifier(tokens)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


class Acme:
    def __init__(self, api: AsyncClient, org: str, kb: str) -> None:
        self.api, self.org, self.kb = api, org, kb

    def h(self, who: str = "alice") -> dict[str, str]:
        return {"Authorization": f"Bearer {who}", "X-Organization-Id": self.org}

    async def start(
        self, size: int = len(CONTENT), name: str = "handbook.txt", who: str = "alice"
    ) -> dict[str, Any]:
        r = await self.api.post(
            f"/v1/knowledge-bases/{self.kb}/uploads",
            json={"filename": name, "content_type": "text/plain", "size_bytes": size},
            headers=self.h(who),
        )
        assert r.status_code == 201, r.text
        body: dict[str, Any] = r.json()
        return body

    async def complete(self, upload_id: str, who: str = "alice", **body: Any) -> httpx.Response:
        return await self.api.post(
            f"/v1/uploads/{upload_id}/complete", json=body, headers=self.h(who)
        )


async def put(upload: dict[str, Any], data: bytes = CONTENT) -> None:
    async with httpx.AsyncClient() as raw:  # straight to MinIO, like a browser
        r = await raw.put(upload["url"], content=data, headers=upload["headers"])
        assert r.status_code == 200, r.text


@pytest.fixture
async def acme(api: AsyncClient) -> Acme:
    owner = {"Authorization": "Bearer alice"}
    org = (
        await api.post("/v1/organizations", json={"name": "Acme", "slug": "acme"}, headers=owner)
    ).json()["id"]
    invite = await api.post(
        f"/v1/organizations/{org}/invitations", json={"email": "bob@acme.test"}, headers=owner
    )
    token = invite.json()["accept_url"].rsplit("/", 1)[1]
    await api.post(f"/v1/invitations/{token}/accept", headers={"Authorization": "Bearer bob"})
    kb = (
        await api.post(
            "/v1/knowledge-bases", json={"name": "HR"}, headers={**owner, "X-Organization-Id": org}
        )
    ).json()["id"]
    return Acme(api, org, kb)


async def count(admin: asyncpg.Connection, table: str) -> int:
    return await admin.fetchval(f"SELECT count(*) FROM {table}")  # type: ignore[no-any-return]  # noqa: S608


# --------------------------------------------------------------------------- happy path


async def test_presign_put_complete_creates_everything_atomically(
    acme: Acme, admin: asyncpg.Connection
) -> None:
    upload = await acme.start()
    assert upload["headers"] == {"Content-Type": "text/plain"}
    await put(upload)

    done = await acme.complete(
        upload["upload_id"], title="Employee handbook", classification="internal"
    )

    assert done.status_code == 200, done.text
    body = done.json()
    assert body["version_number"] == 1
    version = await admin.fetchrow(
        "SELECT object_key, size_bytes, integrity_status, ingestion_status "
        "FROM document_versions WHERE id = $1",
        uuid.UUID(body["document_version_id"]),
    )
    assert version is not None
    assert version["object_key"] == f"{acme.org}/{acme.kb}/{upload['upload_id']}/original"
    assert (version["size_bytes"], version["integrity_status"], version["ingestion_status"]) == (
        len(CONTENT),
        "pending",
        "RECEIVED",
    )
    assert (
        await admin.fetchval(
            "SELECT state FROM ingestion_jobs WHERE id = $1", uuid.UUID(body["ingestion_job_id"])
        )
        == "RECEIVED"
    )
    event = await admin.fetchrow(
        "SELECT event_type, aggregate_id, payload_json FROM outbox_events "
        "WHERE event_type = 'ingestion.requested'"
    )
    assert event is not None
    assert event["aggregate_id"] == body["ingestion_job_id"]
    assert (
        await admin.fetchval("SELECT count(*) FROM audit_events WHERE action = 'document.uploaded'")
        == 1
    )

    document = (await acme.api.get(f"/v1/documents/{body['document_id']}", headers=acme.h())).json()
    assert (document["title"], document["ingestion_state"], document["latest_version_number"]) == (
        "Employee handbook",
        "RECEIVED",
        1,
    )
    job = (
        await acme.api.get(f"/v1/ingestion-jobs/{body['ingestion_job_id']}", headers=acme.h())
    ).json()
    assert (job["state"], job["document_id"]) == ("RECEIVED", body["document_id"])


async def test_double_complete_is_idempotent(acme: Acme, admin: asyncpg.Connection) -> None:
    upload = await acme.start()
    await put(upload)
    first = await acme.complete(upload["upload_id"])
    second = await acme.complete(upload["upload_id"])

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    for table in ("documents", "document_versions", "ingestion_jobs", "outbox_events"):
        assert await count(admin, table) == 1, table


async def test_replacement_creates_the_next_version(acme: Acme, admin: asyncpg.Connection) -> None:
    upload = await acme.start()
    await put(upload)
    doc_id = (await acme.complete(upload["upload_id"])).json()["document_id"]

    replacement = await acme.api.post(
        f"/v1/documents/{doc_id}/versions",
        json={
            "filename": "handbook-2026.txt",
            "content_type": "text/plain",
            "size_bytes": len(CONTENT),
        },
        headers=acme.h(),
    )
    assert replacement.status_code == 201
    await put(replacement.json())
    second = (await acme.complete(replacement.json()["upload_id"])).json()

    assert (second["document_id"], second["version_number"]) == (doc_id, 2)
    versions = (await acme.api.get(f"/v1/documents/{doc_id}/versions", headers=acme.h())).json()
    assert [v["version_number"] for v in versions] == [2, 1]
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM audit_events WHERE action = 'document.version_created'"
        )
        == 1
    )


# --------------------------------------------------------------------------- rejections


async def test_size_mismatch_is_rejected_and_the_object_discarded(
    acme: Acme, admin: asyncpg.Connection, app: FastAPI
) -> None:
    upload = await acme.start(size=len(CONTENT) + 10)
    await put(upload)  # fewer bytes than declared

    response = await acme.complete(upload["upload_id"])

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "size_mismatch"
    assert await count(admin, "documents") == 0
    store = app.state.object_store
    key = f"{acme.org}/{acme.kb}/{upload['upload_id']}/original"
    assert await store.head(app.state.settings.s3_bucket_quarantine, key) is None


async def test_complete_before_the_put_is_409(acme: Acme) -> None:
    upload = await acme.start()
    response = await acme.complete(upload["upload_id"])
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "upload_not_received"


async def test_expired_upload_is_410(acme: Acme, admin: asyncpg.Connection) -> None:
    upload = await acme.start()
    await put(upload)
    await admin.execute(
        "UPDATE uploads SET expires_at = $1 WHERE id = $2",
        datetime.now(UTC) - timedelta(minutes=1),
        uuid.UUID(upload["upload_id"]),
    )
    response = await acme.complete(upload["upload_id"])
    assert response.status_code == 410
    assert response.json()["error"]["code"] == "upload_expired"


@pytest.mark.parametrize(
    ("payload", "status", "code"),
    [
        (
            {"filename": "run.exe", "content_type": "application/octet-stream", "size_bytes": 10},
            422,
            "unsupported_file_type",
        ),
        (
            {"filename": "no-extension", "content_type": "text/plain", "size_bytes": 10},
            422,
            "unsupported_file_type",
        ),
        (
            {"filename": "big.pdf", "content_type": "application/pdf", "size_bytes": 10**10},
            413,
            "file_too_large",
        ),
    ],
)
async def test_declared_files_are_checked_before_presigning(
    acme: Acme, admin: asyncpg.Connection, payload: dict[str, Any], status: int, code: str
) -> None:
    response = await acme.api.post(
        f"/v1/knowledge-bases/{acme.kb}/uploads", json=payload, headers=acme.h()
    )
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert await count(admin, "uploads") == 0


async def test_members_without_document_upload_are_403(acme: Acme) -> None:
    response = await acme.api.post(
        f"/v1/knowledge-bases/{acme.kb}/uploads",
        json={"filename": "a.txt", "content_type": "text/plain", "size_bytes": 5},
        headers=acme.h("bob"),
    )
    assert response.status_code == 403


async def test_failure_mid_transaction_persists_nothing(
    acme: Acme, admin: asyncpg.Connection, app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S13: if anything fails after the document row is written, the whole completion rolls back
    and the upload can be completed again."""
    upload = await acme.start()
    await put(upload)

    async def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected failure")

    monkeypatch.setattr("app.services.documents.outbox.emit", boom)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False), base_url="http://test"
    ) as client:
        failed = await client.post(
            f"/v1/uploads/{upload['upload_id']}/complete", json={}, headers=acme.h()
        )
    assert failed.status_code == 500
    for table in ("documents", "document_versions", "ingestion_jobs", "outbox_events"):
        assert await count(admin, table) == 0, table
    assert (
        await admin.fetchval(
            "SELECT status FROM uploads WHERE id = $1", uuid.UUID(upload["upload_id"])
        )
        == "pending"
    )

    monkeypatch.undo()
    assert (await acme.complete(upload["upload_id"])).status_code == 200


# --------------------------------------------------------------------------- isolation


async def test_uploads_and_documents_are_invisible_across_orgs_and_users(
    acme: Acme, api: AsyncClient
) -> None:
    upload = await acme.start()
    await put(upload)

    # Another member of the same org can't complete alice's upload.
    assert (await acme.complete(upload["upload_id"], who="bob")).status_code in {403, 404}

    globex = (
        await api.post(
            "/v1/organizations",
            json={"name": "Globex", "slug": "globex"},
            headers={"Authorization": "Bearer carol"},
        )
    ).json()["id"]
    carol = {"Authorization": "Bearer carol", "X-Organization-Id": globex}
    assert (
        await api.post(f"/v1/uploads/{upload['upload_id']}/complete", json={}, headers=carol)
    ).status_code == 404

    doc_id = (await acme.complete(upload["upload_id"])).json()["document_id"]
    assert (await api.get(f"/v1/documents/{doc_id}", headers=carol)).status_code == 404
    assert (
        await api.get(f"/v1/knowledge-bases/{acme.kb}/documents", headers=carol)
    ).status_code == 404


async def test_restricted_kb_documents_are_404_for_non_acl_members(acme: Acme) -> None:
    upload = await acme.start()
    await put(upload)
    doc_id = (await acme.complete(upload["upload_id"])).json()["document_id"]
    assert (await acme.api.get(f"/v1/documents/{doc_id}", headers=acme.h("bob"))).status_code == 200

    await acme.api.patch(
        f"/v1/knowledge-bases/{acme.kb}", json={"visibility": "restricted"}, headers=acme.h()
    )

    assert (await acme.api.get(f"/v1/documents/{doc_id}", headers=acme.h("bob"))).status_code == 404
    assert (
        await acme.api.get(f"/v1/knowledge-bases/{acme.kb}/documents", headers=acme.h("bob"))
    ).status_code == 404


# --------------------------------------------------------------------------- reads & delete


async def test_listing_pages_filters_and_delete(acme: Acme, admin: asyncpg.Connection) -> None:
    ids = []
    for name in ("charlie.txt", "alpha.txt", "bravo.txt"):
        upload = await acme.start(name=name)
        await put(upload)
        ids.append((await acme.complete(upload["upload_id"])).json()["document_id"])

    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, str | int] = {"limit": 2, "sort": "title"}
        if cursor:
            params["cursor"] = cursor
        page = (
            await acme.api.get(
                f"/v1/knowledge-bases/{acme.kb}/documents", params=params, headers=acme.h()
            )
        ).json()
        seen += [d["title"] for d in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == ["alpha", "bravo", "charlie"]

    assert (await acme.api.delete(f"/v1/documents/{ids[0]}", headers=acme.h())).status_code == 204
    archived = await acme.api.get(
        f"/v1/knowledge-bases/{acme.kb}/documents", params={"status": "archived"}, headers=acme.h()
    )
    assert [d["id"] for d in archived.json()["items"]] == [ids[0]]
    assert (
        await acme.api.delete(f"/v1/documents/{ids[1]}", headers=acme.h("bob"))
    ).status_code == 403
    assert (
        await admin.fetchval("SELECT count(*) FROM audit_events WHERE action = 'document.archived'")
        == 1
    )
