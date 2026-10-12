"""Knowledge-base lifecycle and access control through the API (T2.1, S12)."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
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
PEOPLE = ("alice", "bob", "carol", "dave")


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
async def api(migrated_settings: Settings, admin: asyncpg.Connection) -> AsyncIterator[AsyncClient]:
    app: FastAPI = create_app(migrated_settings)
    tokens = {
        n: VerifiedToken(
            issuer=ISSUER,
            subject=f"{n}-sub",
            email=f"{n}@acme.test",
            claims={"email_verified": True},
        )
        for n in PEOPLE
    }
    app.dependency_overrides[get_identity_verifier] = lambda: FakeIdentityVerifier(tokens)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


class Org:
    """Acme with alice (owner), bob (member, in group HR), carol (member); dave is outside."""

    def __init__(
        self, api: AsyncClient, org_id: uuid.UUID, users: dict[str, uuid.UUID], hr: uuid.UUID
    ):
        self.api, self.id, self.users, self.hr = api, org_id, users, hr

    def h(self, who: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {who}", "X-Organization-Id": str(self.id)}

    async def create_kb(
        self, name: str = "HR policies", visibility: str = "organization"
    ) -> dict[str, Any]:
        r = await self.api.post(
            "/v1/knowledge-bases",
            json={"name": name, "visibility": visibility},
            headers=self.h("alice"),
        )
        assert r.status_code == 201, r.text
        body: dict[str, Any] = r.json()
        return body


@pytest.fixture
async def org(api: AsyncClient) -> Org:
    async def uid(who: str) -> uuid.UUID:
        return uuid.UUID(
            (await api.get("/v1/me", headers={"Authorization": f"Bearer {who}"})).json()["user"][
                "id"
            ]
        )

    created = await api.post(
        "/v1/organizations",
        json={"name": "Acme", "slug": "acme"},
        headers={"Authorization": "Bearer alice"},
    )
    org_id = uuid.UUID(created.json()["id"])
    owner = {"Authorization": "Bearer alice"}
    users = {"alice": await uid("alice")}
    for who in ("bob", "carol"):
        invite = await api.post(
            f"/v1/organizations/{org_id}/invitations",
            json={"email": f"{who}@acme.test"},
            headers=owner,
        )
        token = invite.json()["accept_url"].rsplit("/", 1)[1]
        await api.post(
            f"/v1/invitations/{token}/accept", headers={"Authorization": f"Bearer {who}"}
        )
        users[who] = await uid(who)
    users["dave"] = await uid("dave")
    hr = (
        await api.post(f"/v1/organizations/{org_id}/groups", json={"name": "HR"}, headers=owner)
    ).json()["id"]
    await api.post(
        f"/v1/organizations/{org_id}/groups/{hr}/members",
        json={"user_id": str(users["bob"])},
        headers=owner,
    )
    return Org(api, org_id, users, uuid.UUID(hr))


async def count(admin: asyncpg.Connection, sql: str, *args: object) -> int:
    return await admin.fetchval(sql, *args)  # type: ignore[no-any-return]


# --------------------------------------------------------------------------- lifecycle


async def test_kb_crud_lifecycle_is_audited(org: Org, admin: asyncpg.Connection) -> None:
    kb = await org.create_kb("HR Policies!")
    assert kb["slug"] == "hr-policies"
    assert kb["can_manage"] is True
    assert kb["document_count"] == 0
    # Slugs stay unique per org.
    assert (await org.create_kb("HR policies"))["slug"] == "hr-policies-2"
    sources = await count(
        admin,
        "SELECT count(*) FROM data_sources WHERE knowledge_base_id = $1 AND type = 'upload'",
        uuid.UUID(kb["id"]),
    )
    assert sources == 1

    url = f"/v1/knowledge-bases/{kb['id']}"
    patched = await org.api.patch(url, json={"description": "Policies"}, headers=org.h("alice"))
    assert patched.json()["description"] == "Policies"
    assert (await org.api.get(url, headers=org.h("carol"))).status_code == 200

    assert (await org.api.delete(url, headers=org.h("alice"))).status_code == 204
    assert (await org.api.delete(url, headers=org.h("alice"))).status_code == 204  # idempotent
    listed = (await org.api.get("/v1/knowledge-bases", headers=org.h("alice"))).json()
    assert kb["id"] not in {k["id"] for k in listed}
    assert (await org.api.get(url, headers=org.h("alice"))).json()["archived_at"] is not None

    for action, expected in (("kb.created", 2), ("kb.updated", 1), ("kb.archived", 1)):
        assert (
            await count(admin, "SELECT count(*) FROM audit_events WHERE action = $1", action)
            == expected
        )


async def test_members_cannot_create_or_manage(org: Org) -> None:
    create = await org.api.post("/v1/knowledge-bases", json={"name": "Mine"}, headers=org.h("bob"))
    assert create.status_code == 403
    kb = await org.create_kb()
    url = f"/v1/knowledge-bases/{kb['id']}"
    assert (await org.api.patch(url, json={"name": "x"}, headers=org.h("bob"))).status_code == 403
    assert (await org.api.delete(url, headers=org.h("bob"))).status_code == 403
    assert (await org.api.get(f"{url}/permissions", headers=org.h("bob"))).status_code == 403
    assert (await org.api.get(url, headers=org.h("bob"))).json()["can_manage"] is False


# --------------------------------------------------------------------------- restricted KBs


async def test_restricted_kb_is_invisible_without_an_acl_match(org: Org) -> None:
    kb = await org.create_kb("Compensation", "restricted")
    url = f"/v1/knowledge-bases/{kb['id']}"

    for who in ("bob", "carol"):
        assert kb["id"] not in {
            k["id"] for k in (await org.api.get("/v1/knowledge-bases", headers=org.h(who))).json()
        }
        assert (await org.api.get(url, headers=org.h(who))).status_code == 404
        # Non-visible KBs are 404 for writes too, never 403.
        assert (await org.api.patch(url, json={"name": "x"}, headers=org.h(who))).status_code == 404

    # Grant the HR group: bob (in HR) sees it, carol doesn't.
    put = await org.api.put(
        f"{url}/permissions",
        json={
            "entries": [
                {"principal_type": "group", "principal_id": str(org.hr), "permission": "query"},
                {
                    "principal_type": "user",
                    "principal_id": str(org.users["alice"]),
                    "permission": "manage",
                },
            ]
        },
        headers=org.h("alice"),
    )
    assert put.status_code == 200
    assert (await org.api.get(url, headers=org.h("bob"))).status_code == 200
    assert (await org.api.get(url, headers=org.h("carol"))).status_code == 404

    # A role entry opens it to every member.
    await org.api.put(
        f"{url}/permissions",
        json={
            "entries": [
                {"principal_type": "role", "principal_id": "member", "permission": "query"},
                {
                    "principal_type": "user",
                    "principal_id": str(org.users["alice"]),
                    "permission": "manage",
                },
            ]
        },
        headers=org.h("alice"),
    )
    assert (await org.api.get(url, headers=org.h("carol"))).status_code == 200


async def test_manage_acl_entry_lets_a_member_manage(org: Org) -> None:
    kb = await org.create_kb("Support", "restricted")
    url = f"/v1/knowledge-bases/{kb['id']}"
    await org.api.put(
        f"{url}/permissions",
        json={
            "entries": [
                {
                    "principal_type": "user",
                    "principal_id": str(org.users["carol"]),
                    "permission": "manage",
                }
            ]
        },
        headers=org.h("alice"),
    )
    carol = await org.api.get(url, headers=org.h("carol"))
    assert carol.json()["can_manage"] is True
    assert (
        await org.api.patch(url, json={"description": "ok"}, headers=org.h("carol"))
    ).status_code == 200


async def test_permission_changes_emit_acl_changed_and_audit(
    org: Org, admin: asyncpg.Connection
) -> None:
    kb = await org.create_kb("Engineering", "restricted")
    kb_id = uuid.UUID(kb["id"])
    entries = [{"principal_type": "group", "principal_id": str(org.hr), "permission": "query"}]
    first = await org.api.put(
        f"/v1/knowledge-bases/{kb_id}/permissions",
        json={"entries": entries},
        headers=org.h("alice"),
    )
    again = await org.api.put(
        f"/v1/knowledge-bases/{kb_id}/permissions",
        json={"entries": entries},
        headers=org.h("alice"),
    )
    assert first.json()["entries"] == again.json()["entries"] == entries
    assert first.json()["propagated_at"] is None

    events = await count(
        admin,
        "SELECT count(*) FROM outbox_events WHERE event_type = 'acl.changed' AND aggregate_id = $1",
        str(kb_id),
    )
    assert events == 1  # the identical second PUT is a no-op
    assert (
        await count(
            admin, "SELECT count(*) FROM audit_events WHERE action = 'kb.permissions_changed'"
        )
        == 1
    )

    await org.api.patch(
        f"/v1/knowledge-bases/{kb_id}", json={"visibility": "organization"}, headers=org.h("alice")
    )
    assert (
        await count(
            admin,
            "SELECT count(*) FROM outbox_events "
            "WHERE event_type = 'acl.changed' AND aggregate_id = $1",
            str(kb_id),
        )
        == 2
    )


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param({"principal_type": "user", "principal_id": "OUTSIDER"}, id="non-member-user"),
        pytest.param(
            {"principal_type": "group", "principal_id": "FOREIGN_GROUP"}, id="other-orgs-group"
        ),
        pytest.param({"principal_type": "role", "principal_id": "emperor"}, id="unknown-role"),
        pytest.param({"principal_type": "user", "principal_id": "not-a-uuid"}, id="malformed-id"),
    ],
)
async def test_foreign_or_unknown_principals_are_rejected(
    org: Org, admin: asyncpg.Connection, entry: dict[str, str]
) -> None:
    other_org = (
        await org.api.post(
            "/v1/organizations",
            json={"name": "Globex", "slug": "globex"},
            headers={"Authorization": "Bearer dave"},
        )
    ).json()["id"]
    foreign_group = (
        await org.api.post(
            f"/v1/organizations/{other_org}/groups",
            json={"name": "HR"},
            headers={"Authorization": "Bearer dave"},
        )
    ).json()["id"]
    principal = {"OUTSIDER": str(org.users["dave"]), "FOREIGN_GROUP": foreign_group}.get(
        entry["principal_id"], entry["principal_id"]
    )
    kb = await org.create_kb("Legal", "restricted")

    response = await org.api.put(
        f"/v1/knowledge-bases/{kb['id']}/permissions",
        json={"entries": [{**entry, "principal_id": principal, "permission": "query"}]},
        headers=org.h("alice"),
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_principal"
    assert (
        await count(
            admin, "SELECT count(*) FROM audit_events WHERE action = 'kb.permissions_changed'"
        )
        == 0
    )


# --------------------------------------------------------------------------- isolation


async def test_other_orgs_kbs_are_404(org: Org) -> None:
    other = (
        await org.api.post(
            "/v1/organizations",
            json={"name": "Globex", "slug": "globex"},
            headers={"Authorization": "Bearer dave"},
        )
    ).json()["id"]
    foreign = (
        await org.api.post(
            "/v1/knowledge-bases",
            json={"name": "Secrets"},
            headers={"Authorization": "Bearer dave", "X-Organization-Id": other},
        )
    ).json()["id"]

    url = f"/v1/knowledge-bases/{foreign}"
    assert (await org.api.get(url, headers=org.h("alice"))).status_code == 404
    assert (await org.api.patch(url, json={"name": "x"}, headers=org.h("alice"))).status_code == 404
    assert (await org.api.delete(url, headers=org.h("alice"))).status_code == 404
    assert (await org.api.get(f"{url}/permissions", headers=org.h("alice"))).status_code == 404
    assert foreign not in {
        k["id"] for k in (await org.api.get("/v1/knowledge-bases", headers=org.h("alice"))).json()
    }


# --------------------------------------------------------------------------- review #25 fixes


async def test_concurrent_acl_replacements_never_merge(org: Org) -> None:
    """Review #25 (HIGH): the final ACL is exactly one PUT's payload, never their union."""
    kb = await org.create_kb("Board", "restricted")
    url = f"/v1/knowledge-bases/{kb['id']}/permissions"
    alice_manage = {
        "principal_type": "user",
        "principal_id": str(org.users["alice"]),
        "permission": "manage",
    }
    payload_a = [
        alice_manage,
        {"principal_type": "group", "principal_id": str(org.hr), "permission": "query"},
    ]
    payload_b = [
        alice_manage,
        {"principal_type": "user", "principal_id": str(org.users["carol"]), "permission": "query"},
    ]

    for _ in range(5):
        first, second = await asyncio.gather(
            org.api.put(url, json={"entries": payload_a}, headers=org.h("alice")),
            org.api.put(url, json={"entries": payload_b}, headers=org.h("alice")),
        )
        assert first.status_code == second.status_code == 200
        final = (await org.api.get(url, headers=org.h("alice"))).json()["entries"]
        key = lambda e: (e["principal_type"], e["principal_id"], e["permission"])  # noqa: E731
        assert sorted(final, key=key) in (sorted(payload_a, key=key), sorted(payload_b, key=key))


async def test_concurrent_same_name_creations_get_distinct_slugs(org: Org) -> None:
    """Review #25 (MEDIUM): no IntegrityError/500 when two KBs with one name race."""
    responses = await asyncio.gather(
        *(
            org.api.post("/v1/knowledge-bases", json={"name": "Shared"}, headers=org.h("alice"))
            for _ in range(4)
        )
    )
    assert {r.status_code for r in responses} == {201}
    assert sorted(r.json()["slug"] for r in responses) == [
        "shared",
        "shared-2",
        "shared-3",
        "shared-4",
    ]
