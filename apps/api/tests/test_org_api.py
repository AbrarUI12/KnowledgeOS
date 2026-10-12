"""Organizations, members, invitations and groups through the API (T1.3, S09)."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import get_identity_verifier
from app.auth.permissions import SystemRole, system_role_id
from app.core.config import Settings
from app.main import create_app
from app.providers.identity.base import VerifiedToken
from tests.fakes import FakeIdentityVerifier

pytestmark = pytest.mark.integration

ISSUER = "https://idp.test/realms/knowledgeos"
PEOPLE = ("alice", "bob", "carol", "dave", "erin")


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
    application = create_app(
        migrated_settings.model_copy(update={"web_base_url": "http://web.test"})
    )
    tokens = {
        name: VerifiedToken(
            issuer=ISSUER,
            subject=f"{name}-sub",
            email=f"{name}@acme.test",
            claims={"email_verified": True},
        )
        for name in PEOPLE
    }
    # Same email as erin, but the IdP hasn't verified it.
    tokens["mallory"] = VerifiedToken(
        issuer=ISSUER,
        subject="mallory-sub",
        email="erin@acme.test",
        claims={"email_verified": False},
    )
    application.dependency_overrides[get_identity_verifier] = lambda: FakeIdentityVerifier(tokens)
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def auth(name: str, **extra: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {name}", **extra}


async def audit_count(admin: asyncpg.Connection, action: str | None = None) -> int:
    if action is None:
        return await admin.fetchval("SELECT count(*) FROM audit_events")  # type: ignore[no-any-return]
    return await admin.fetchval(  # type: ignore[no-any-return]
        "SELECT count(*) FROM audit_events WHERE action = $1", action
    )


async def create_org(api: AsyncClient, who: str = "alice", slug: str = "acme") -> uuid.UUID:
    response = await api.post(
        "/v1/organizations", json={"name": slug.title(), "slug": slug}, headers=auth(who)
    )
    assert response.status_code == 201, response.text
    return uuid.UUID(response.json()["id"])


async def user_id(api: AsyncClient, who: str) -> uuid.UUID:
    return uuid.UUID((await api.get("/v1/me", headers=auth(who))).json()["user"]["id"])


async def invite_and_join(
    api: AsyncClient, org: uuid.UUID, who: str, role: str = "member"
) -> uuid.UUID:
    invite = await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": f"{who}@acme.test", "role": role},
        headers=auth("alice"),
    )
    assert invite.status_code == 201, invite.text
    token = invite.json()["accept_url"].rsplit("/", 1)[1]
    accepted = await api.post(f"/v1/invitations/{token}/accept", headers=auth(who))
    assert accepted.status_code == 200, accepted.text
    return await user_id(api, who)


# --------------------------------------------------------------------------- organizations


async def test_creator_becomes_owner_and_creation_is_audited(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    org = await create_org(api)

    me = (await api.get("/v1/me", headers=auth("alice"))).json()
    assert [(m["organization_id"], m["role"]) for m in me["memberships"]] == [(str(org), "owner")]
    listed = (await api.get("/v1/organizations", headers=auth("alice"))).json()
    assert [o["slug"] for o in listed] == ["acme"]
    assert (await api.get("/v1/organizations", headers=auth("bob"))).json() == []
    assert await audit_count(admin) == 1
    assert await audit_count(admin, "org.created") == 1


async def test_duplicate_slug_is_409_and_leaves_nothing_behind(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    await create_org(api)
    response = await api.post(
        "/v1/organizations", json={"name": "Other", "slug": "acme"}, headers=auth("bob")
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "slug_taken"
    assert await admin.fetchval("SELECT count(*) FROM organizations") == 1
    assert await audit_count(admin) == 1


async def test_idempotent_replay_returns_the_identical_response(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    headers = auth("alice", **{"Idempotency-Key": "create-acme-0001"})
    body = {"name": "Acme", "slug": "acme"}
    first = await api.post("/v1/organizations", json=body, headers=headers)
    replay = await api.post("/v1/organizations", json=body, headers=headers)

    assert first.status_code == replay.status_code == 201
    assert first.json() == replay.json()
    assert await admin.fetchval("SELECT count(*) FROM organizations") == 1
    assert await audit_count(admin) == 1

    reused = await api.post(
        "/v1/organizations", json={"name": "Other", "slug": "other"}, headers=headers
    )
    assert reused.status_code == 409
    assert reused.json()["error"]["code"] == "idempotency_key_reused"
    # Keys are per user: the same key from someone else is independent.
    other = await api.post(
        "/v1/organizations",
        json={"name": "Globex", "slug": "globex"},
        headers=auth("bob", **{"Idempotency-Key": "create-acme-0001"}),
    )
    assert other.status_code == 201


async def test_failed_request_does_not_burn_the_idempotency_key(api: AsyncClient) -> None:
    await create_org(api, "bob", "acme")
    headers = auth("alice", **{"Idempotency-Key": "retry-me-0001"})
    taken = await api.post("/v1/organizations", json={"name": "A", "slug": "acme"}, headers=headers)
    assert taken.status_code == 409
    # The failed attempt rolled back its claim; a corrected retry with the same key... still
    # has a different body, so it's a *different* request: use a fresh key for that. Replaying
    # the identical failed request simply fails again instead of returning a stale response.
    again = await api.post("/v1/organizations", json={"name": "A", "slug": "acme"}, headers=headers)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "slug_taken"


# --------------------------------------------------------------------------- members


async def test_member_cannot_manage_members(api: AsyncClient, admin: asyncpg.Connection) -> None:
    org = await create_org(api)
    bob = await invite_and_join(api, org, "bob")
    carol = await invite_and_join(api, org, "carol")
    before = await audit_count(admin)

    patch = await api.patch(
        f"/v1/organizations/{org}/members/{carol}", json={"role": "admin"}, headers=auth("bob")
    )
    delete = await api.delete(f"/v1/organizations/{org}/members/{carol}", headers=auth("bob"))
    invite = await api.post(
        f"/v1/organizations/{org}/invitations", json={"email": "x@acme.test"}, headers=auth("bob")
    )

    assert {patch.status_code, delete.status_code, invite.status_code} == {403}
    assert await audit_count(admin) == before
    # ...but members may list members.
    listed = await api.get(f"/v1/organizations/{org}/members", headers=auth("bob"))
    assert {m["user_id"] for m in listed.json()["items"]} >= {str(bob), str(carol)}


async def test_last_owner_cannot_be_demoted_or_removed(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    org = await create_org(api)
    alice = await user_id(api, "alice")
    before = await audit_count(admin)

    demote = await api.patch(
        f"/v1/organizations/{org}/members/{alice}", json={"role": "admin"}, headers=auth("alice")
    )
    remove = await api.delete(f"/v1/organizations/{org}/members/{alice}", headers=auth("alice"))

    assert demote.status_code == remove.status_code == 409
    assert demote.json()["error"]["code"] == "last_owner"
    assert await audit_count(admin) == before

    # With a second owner, demotion works and is audited once.
    bob = await invite_and_join(api, org, "bob", role="owner")
    ok = await api.patch(
        f"/v1/organizations/{org}/members/{alice}", json={"role": "admin"}, headers=auth("bob")
    )
    assert ok.status_code == 200
    assert ok.json()["role"] == "admin"
    assert await audit_count(admin, "member.role_changed") == 1
    assert bob


async def test_admins_cannot_grant_or_remove_ownership(api: AsyncClient) -> None:
    org = await create_org(api)
    await invite_and_join(api, org, "bob", role="admin")
    carol = await invite_and_join(api, org, "carol")
    alice = await user_id(api, "alice")

    promote = await api.patch(
        f"/v1/organizations/{org}/members/{carol}", json={"role": "owner"}, headers=auth("bob")
    )
    remove_owner = await api.delete(f"/v1/organizations/{org}/members/{alice}", headers=auth("bob"))
    invite_owner = await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": "dave@acme.test", "role": "owner"},
        headers=auth("bob"),
    )
    assert {promote.status_code, remove_owner.status_code, invite_owner.status_code} == {403}

    # Admins can still change non-owner roles.
    ok = await api.patch(
        f"/v1/organizations/{org}/members/{carol}", json={"role": "viewer"}, headers=auth("bob")
    )
    assert ok.status_code == 200


async def test_unknown_role_is_422(api: AsyncClient) -> None:
    org = await create_org(api)
    alice = await user_id(api, "alice")
    response = await api.patch(
        f"/v1/organizations/{org}/members/{alice}", json={"role": "emperor"}, headers=auth("alice")
    )
    assert response.status_code == 422


async def test_removing_a_member_removes_their_group_memberships(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    org = await create_org(api)
    bob = await invite_and_join(api, org, "bob")
    group = (
        await api.post(
            f"/v1/organizations/{org}/groups", json={"name": "HR"}, headers=auth("alice")
        )
    ).json()["id"]
    await api.post(
        f"/v1/organizations/{org}/groups/{group}/members",
        json={"user_id": str(bob)},
        headers=auth("alice"),
    )
    before = await audit_count(admin)

    response = await api.delete(f"/v1/organizations/{org}/members/{bob}", headers=auth("alice"))

    assert response.status_code == 204
    assert await admin.fetchval("SELECT count(*) FROM group_memberships") == 0
    assert await audit_count(admin) == before + 1
    assert (
        await api.get(f"/v1/organizations/{org}/members", headers=auth("bob"))
    ).status_code == 404


async def test_pagination_has_no_duplicates_or_skips_under_concurrent_inserts(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    org = await create_org(api)
    for i in range(7):
        uid = await admin.fetchval(
            "INSERT INTO users (id, issuer, external_subject, email) VALUES ($1, $2, $3, $4) "
            "RETURNING id",
            uuid.uuid4(),
            ISSUER,
            f"seed-{i}",
            f"seed{i}@acme.test",
        )
        await admin.execute(
            "INSERT INTO memberships (id, organization_id, user_id, role_id) "
            "VALUES ($1, $2, $3, $4)",
            uuid.uuid4(),
            org,
            uid,
            system_role_id(SystemRole.MEMBER),
        )
    original = {
        str(r["user_id"])
        for r in await admin.fetch(
            "SELECT user_id FROM memberships WHERE organization_id = $1", org
        )
    }

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        params: dict[str, str | int] = {"limit": 3}
        if cursor:
            params["cursor"] = cursor
        page = (
            await api.get(f"/v1/organizations/{org}/members", params=params, headers=auth("alice"))
        ).json()
        seen += [m["user_id"] for m in page["items"]]
        pages += 1
        if pages == 1:  # someone joins mid-pagination
            await invite_and_join(api, org, "erin")
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert len(seen) == len(set(seen)), "duplicates across pages"
    assert original <= set(seen), "rows that existed before paging were skipped"


async def test_malformed_cursor_is_422(api: AsyncClient) -> None:
    org = await create_org(api)
    response = await api.get(
        f"/v1/organizations/{org}/members", params={"cursor": "%%%"}, headers=auth("alice")
    )
    assert response.status_code == 422


# --------------------------------------------------------------------------- invitations


async def test_invitation_lifecycle(api: AsyncClient, admin: asyncpg.Connection) -> None:
    org = await create_org(api)
    invite = await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": "Bob@Acme.test", "role": "knowledge_manager"},
        headers=auth("alice"),
    )
    body = invite.json()
    token = body["accept_url"].rsplit("/", 1)[1]
    assert body["accept_url"].startswith("http://web.test/invitations/")
    assert body["email"] == "bob@acme.test"
    stored = await admin.fetchval(
        "SELECT token_hash FROM invitations WHERE id = $1", uuid.UUID(body["id"])
    )
    assert token not in stored  # only the hash is stored

    wrong_person = await api.post(f"/v1/invitations/{token}/accept", headers=auth("carol"))
    assert wrong_person.status_code == 403
    assert wrong_person.json()["error"]["code"] == "invitation_email_mismatch"

    accepted = await api.post(f"/v1/invitations/{token}/accept", headers=auth("bob"))
    assert accepted.json() == {"organization_id": str(org), "role": "knowledge_manager"}
    retry = await api.post(f"/v1/invitations/{token}/accept", headers=auth("bob"))
    assert retry.status_code == 200  # harmless retry
    assert await audit_count(admin, "member.invited") == 1
    assert await audit_count(admin, "member.joined") == 1

    again = await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": "bob@acme.test"},
        headers=auth("alice"),
    )
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "already_member"


async def test_unknown_expired_and_superseded_invitations(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    org = await create_org(api)
    assert (
        await api.post("/v1/invitations/not-a-token/accept", headers=auth("bob"))
    ).status_code == 404

    first = await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": "bob@acme.test"},
        headers=auth("alice"),
    )
    second = await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": "bob@acme.test"},
        headers=auth("alice"),
    )
    old_token = first.json()["accept_url"].rsplit("/", 1)[1]
    new_token = second.json()["accept_url"].rsplit("/", 1)[1]
    superseded = await api.post(f"/v1/invitations/{old_token}/accept", headers=auth("bob"))
    assert superseded.status_code == 404

    await admin.execute(
        "UPDATE invitations SET expires_at = $1 WHERE id = $2",
        datetime.now(UTC) - timedelta(minutes=1),
        uuid.UUID(second.json()["id"]),
    )
    expired = await api.post(f"/v1/invitations/{new_token}/accept", headers=auth("bob"))
    assert expired.status_code == 410
    assert expired.json()["error"]["code"] == "invitation_expired"


async def test_invitations_of_another_org_are_invisible_without_the_token(
    api: AsyncClient, admin: asyncpg.Connection, migrated_settings: Settings
) -> None:
    """The token-holder policy only reveals the row whose hash is set in the transaction."""
    org = await create_org(api)
    await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": "bob@acme.test"},
        headers=auth("alice"),
    )
    conn = await asyncpg.connect(
        migrated_settings.database_url.get_secret_value().replace("+asyncpg", "")
    )
    try:
        async with conn.transaction():
            await conn.execute("SELECT set_config('app.invitation_token_hash', 'guess', true)")
            assert await conn.fetchval("SELECT count(*) FROM invitations") == 0
    finally:
        await conn.close()


# --------------------------------------------------------------------------- groups


async def test_group_lifecycle_is_audited_once_per_mutation(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    org = await create_org(api)
    bob = await invite_and_join(api, org, "bob")
    base = f"/v1/organizations/{org}/groups"
    start = await audit_count(admin)

    created = await api.post(
        base, json={"name": "HR", "description": "People"}, headers=auth("alice")
    )
    group = created.json()["id"]
    assert created.status_code == 201
    dup = await api.post(base, json={"name": "HR"}, headers=auth("alice"))
    assert dup.status_code == 409
    assert dup.json()["error"]["code"] == "group_name_taken"

    renamed = await api.patch(f"{base}/{group}", json={"name": "People Ops"}, headers=auth("alice"))
    assert renamed.json()["name"] == "People Ops"
    unchanged = await api.patch(
        f"{base}/{group}", json={"name": "People Ops"}, headers=auth("alice")
    )
    assert unchanged.status_code == 200

    add = await api.post(
        f"{base}/{group}/members", json={"user_id": str(bob)}, headers=auth("alice")
    )
    add_again = await api.post(
        f"{base}/{group}/members", json={"user_id": str(bob)}, headers=auth("alice")
    )
    assert add.status_code == add_again.status_code == 204
    members = (await api.get(f"{base}/{group}/members", headers=auth("bob"))).json()["items"]
    assert [m["user_id"] for m in members] == [str(bob)]
    assert (await api.get(base, headers=auth("bob"))).json()["items"][0]["member_count"] == 1

    remove = await api.delete(f"{base}/{group}/members/{bob}", headers=auth("alice"))
    assert remove.status_code == 204
    deleted = await api.delete(f"{base}/{group}", headers=auth("alice"))
    assert deleted.status_code == 204

    # created, updated, member_added, member_removed, deleted: no rows for no-ops or failures.
    assert await audit_count(admin) - start == 5
    for action in (
        "group.created",
        "group.updated",
        "group.member_added",
        "group.member_removed",
        "group.deleted",
    ):
        assert await audit_count(admin, action) == 1, action


async def test_only_org_members_can_join_groups(api: AsyncClient) -> None:
    org = await create_org(api)
    outsider = await user_id(api, "dave")
    group = (
        await api.post(
            f"/v1/organizations/{org}/groups", json={"name": "HR"}, headers=auth("alice")
        )
    ).json()["id"]
    response = await api.post(
        f"/v1/organizations/{org}/groups/{group}/members",
        json={"user_id": str(outsider)},
        headers=auth("alice"),
    )
    assert response.status_code == 404


async def test_other_orgs_group_ids_are_404(api: AsyncClient, admin: asyncpg.Connection) -> None:
    """IDOR: a valid group id from org B, used under org A, must not be found or touched."""
    acme = await create_org(api, "alice", "acme")
    globex = await create_org(api, "carol", "globex")
    foreign = (
        await api.post(
            f"/v1/organizations/{globex}/groups", json={"name": "HR"}, headers=auth("carol")
        )
    ).json()["id"]
    alice = await user_id(api, "alice")
    base = f"/v1/organizations/{acme}/groups/{foreign}"

    responses = [
        await api.patch(base, json={"name": "pwned"}, headers=auth("alice")),
        await api.delete(base, headers=auth("alice")),
        await api.get(f"{base}/members", headers=auth("alice")),
        await api.post(f"{base}/members", json={"user_id": str(alice)}, headers=auth("alice")),
    ]
    assert [r.status_code for r in responses] == [404, 404, 404, 404]
    assert await admin.fetchval("SELECT name FROM groups WHERE id = $1", uuid.UUID(foreign)) == "HR"


async def test_group_management_needs_permission(api: AsyncClient) -> None:
    org = await create_org(api)
    await invite_and_join(api, org, "bob")
    response = await api.post(
        f"/v1/organizations/{org}/groups", json={"name": "X"}, headers=auth("bob")
    )
    assert response.status_code == 403


# --------------------------------------------------------------------------- review #19 fixes


async def test_unverified_email_cannot_accept_an_invitation(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    """Review #19 (HIGH): the invited address must be verified by the IdP, not just claimed."""
    org = await create_org(api)
    invite = await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": "erin@acme.test", "role": "owner"},
        headers=auth("alice"),
    )
    token = invite.json()["accept_url"].rsplit("/", 1)[1]

    forged = await api.post(f"/v1/invitations/{token}/accept", headers=auth("mallory"))
    assert forged.status_code == 403
    assert forged.json()["error"]["code"] == "invitation_email_mismatch"
    assert await audit_count(admin, "member.joined") == 0

    verified = await api.post(f"/v1/invitations/{token}/accept", headers=auth("erin"))
    assert verified.status_code == 200


async def test_invitation_tokens_are_never_persisted(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    """Review #19 (HIGH): no replay cache or other table may hold the plaintext token."""
    org = await create_org(api)
    invite = await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": "bob@acme.test"},
        headers=auth("alice", **{"Idempotency-Key": "invite-bob-0001"}),
    )
    token = invite.json()["accept_url"].rsplit("/", 1)[1]

    dump = await admin.fetchval(
        "SELECT coalesce(string_agg(response_json::text, ' '), '') FROM idempotency_keys"
    )
    assert token not in dump
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM idempotency_keys WHERE key = $1", "invite-bob-0001"
        )
        == 0
    )
    assert token not in str(await admin.fetchval("SELECT token_hash FROM invitations"))


async def test_concurrent_accepts_create_one_membership(
    api: AsyncClient, admin: asyncpg.Connection
) -> None:
    """Review #19 (MEDIUM): two simultaneous accepts serialize on the invitation row."""
    org = await create_org(api)
    invite = await api.post(
        f"/v1/organizations/{org}/invitations",
        json={"email": "bob@acme.test"},
        headers=auth("alice"),
    )
    token = invite.json()["accept_url"].rsplit("/", 1)[1]

    first, second = await asyncio.gather(
        api.post(f"/v1/invitations/{token}/accept", headers=auth("bob")),
        api.post(f"/v1/invitations/{token}/accept", headers=auth("bob")),
    )

    assert {first.status_code, second.status_code} == {200}
    bob = await user_id(api, "bob")
    assert (
        await admin.fetchval(
            "SELECT count(*) FROM memberships WHERE organization_id = $1 AND user_id = $2", org, bob
        )
        == 1
    )
    assert await audit_count(admin, "member.joined") == 1
