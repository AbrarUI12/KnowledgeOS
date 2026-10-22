# ruff: noqa: E501, F811  (fixtures imported from test_ingestion_stages; long SQL reads better unwrapped)
"""Evidence endpoints (T5.4, S31 backend): content links, chunk context, feedback."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import asyncpg
import pytest

from app.domain.enums import IngestionState
from tests.test_ingestion_ops import join_as, upload_version
from tests.test_ingestion_stages import (  # noqa: F401 (pytest fixtures)
    World,
    admin,
    app,
    store,
    world,
)
from tests.test_search_api import use_search
from tests.test_search_backend import IdentifierChunker

pytestmark = pytest.mark.integration
S = IngestionState
THREE = b"# Policy\n\nFirst paragraph about leave.\n\nSecond paragraph about weeks.\n\nThird paragraph about requests.\n"


async def ready(world: World, data: bytes = THREE, name: str = "policy.md") -> dict[str, Any]:
    job = await world.upload(data, name=name)
    assert await world.run(job, chunker=IdentifierChunker()) is S.READY
    return job


async def chunks(admin: asyncpg.Connection, version: str) -> list[uuid.UUID]:
    return [
        r["id"]
        for r in await admin.fetch(
            "SELECT id FROM chunks WHERE document_version_id = $1 AND NOT is_parent ORDER BY ordinal",
            uuid.UUID(version),
        )
    ]


def content_url(job: dict[str, Any]) -> str:
    return f"/v1/documents/{job['document_id']}/versions/{job['document_version_id']}/content-url"


# --------------------------------------------------------------------------- content URL


async def test_readers_get_a_short_lived_link_to_the_trusted_original(world: World) -> None:
    await join_as(world, "bob", "member")
    job = await ready(world)

    for who in ("alice", "bob"):
        response = await world.api.get(content_url(job), headers=world.h(who))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["url"].startswith(f"memory://kos-trusted/{world.org}/")
        assert body["url"].endswith("/original?get")  # never the quarantine copy
        expires = datetime.fromisoformat(body["expires_at"])
        assert expires - datetime.now(UTC) <= timedelta(minutes=5)


async def test_content_links_need_content_access_and_a_promoted_original(
    world: World, admin: asyncpg.Connection
) -> None:
    await join_as(world, "bob", "admin")
    job = await ready(world)
    alice = (await world.api.get("/v1/me", headers=world.h())).json()["user"]["id"]
    await admin.execute(
        "INSERT INTO document_acl (organization_id, document_id, principal_type, principal_id, permission) VALUES ($1, $2, 'user', $3, 'query')",
        uuid.UUID(world.org), uuid.UUID(job["document_id"]), alice,
    )  # fmt: skip
    # Bob administers the KB but the document is narrowed to Alice: metadata yes, content no.
    assert (await world.api.get(content_url(job), headers=world.h("bob"))).status_code == 403
    assert (await world.api.get(content_url(job), headers=world.h())).status_code == 200

    pending = await world.upload(THREE, name="pending.md")  # completed upload, not yet scanned
    assert (await world.api.get(content_url(pending), headers=world.h())).status_code == 409
    missing = f"/v1/documents/{uuid.uuid4()}/versions/{uuid.uuid4()}/content-url"
    assert (await world.api.get(missing, headers=world.h())).status_code == 404


# --------------------------------------------------------------------------- chunk context


async def test_chunk_context_returns_authorized_neighbors(
    world: World, admin: asyncpg.Connection
) -> None:
    use_search(world)
    job = await ready(world)
    first, second, third = await chunks(admin, job["document_version_id"])

    response = await world.api.get(f"/v1/chunks/{second}/context", headers=world.h())

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["content"] == "Second paragraph about weeks."
    assert body["before"] == ["First paragraph about leave."]
    assert body["after"] == ["Third paragraph about requests."]
    wider = (await world.api.get(f"/v1/chunks/{first}/context?after=2", headers=world.h())).json()
    assert wider["before"] == []
    assert len(wider["after"]) == 2
    assert third  # used above through `after=2`


async def test_chunks_the_caller_couldnt_retrieve_are_not_found(
    world: World, admin: asyncpg.Connection
) -> None:
    use_search(world)
    await join_as(world, "bob", "member")
    v1 = await ready(world)
    old_chunk = (await chunks(admin, v1["document_version_id"]))[0]
    v2 = await upload_version(world, v1["document_id"], THREE + b"\nUpdated.\n")
    assert await world.run(v2, chunker=IdentifierChunker()) is S.READY

    # A superseded version's chunk can't be opened by id.
    assert (
        await world.api.get(f"/v1/chunks/{old_chunk}/context", headers=world.h())
    ).status_code == 404

    # Restrict the KB to Alice: Bob gets 404 for its chunks, never 403.
    alice = (await world.api.get("/v1/me", headers=world.h())).json()["user"]["id"]
    entries = [{"principal_type": "user", "principal_id": alice, "permission": "manage"}]
    await world.api.put(
        f"/v1/knowledge-bases/{world.kb}/permissions", json={"entries": entries}, headers=world.h()
    )
    await world.api.patch(
        f"/v1/knowledge-bases/{world.kb}", json={"visibility": "restricted"}, headers=world.h()
    )
    current = (await chunks(admin, v2["document_version_id"]))[0]
    assert (
        await world.api.get(f"/v1/chunks/{current}/context", headers=world.h("bob"))
    ).status_code == 404
    assert (
        await world.api.get(f"/v1/chunks/{uuid.uuid4()}/context", headers=world.h())
    ).status_code == 404


# --------------------------------------------------------------------------- feedback


async def test_feedback_is_kept_once_per_person_and_only_on_your_own_runs(
    world: World, admin: asyncpg.Connection
) -> None:
    use_search(world)
    await join_as(world, "bob", "member")
    await ready(world)
    run = (
        await world.api.post(
            f"/v1/knowledge-bases/{world.kb}/search", json={"query": "leave"}, headers=world.h()
        )
    ).json()["query_run_id"]
    url = f"/v1/query-runs/{run}/feedback"

    first = await world.api.post(url, json={"rating": "up"}, headers=world.h())
    assert first.status_code == 201, first.text
    again = await world.api.post(
        url,
        json={"rating": "down", "reason_code": "wrong_source", "comment": "old policy"},
        headers=world.h(),
    )
    assert again.json()["id"] == first.json()["id"]  # replaced, not duplicated
    rows = await admin.fetch(
        "SELECT rating, reason_code, comment FROM feedback WHERE query_run_id = $1", uuid.UUID(run)
    )
    assert [tuple(r) for r in rows] == [("down", "wrong_source", "old policy")]

    assert (
        await world.api.post(url, json={"rating": "up"}, headers=world.h("bob"))
    ).status_code == 404
