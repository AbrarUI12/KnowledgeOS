"""Tenant resolution and permission checks through the API (T1.2, S08).

Org-scoped stubs resolve the tenant context before their 501 body, so "reaches the stub" (501)
means "authorized for the organization", and 404 means "not visible".
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

import asyncpg
import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import get_identity_verifier
from app.api.dependencies.tenancy import OrgContext, require_permission
from app.auth.authorization import RequestContext, principal_tokens
from app.auth.permissions import Permission, SystemRole, system_role_id
from app.core.config import Settings
from app.main import create_app
from app.providers.identity.base import VerifiedToken
from tests.fakes import FakeIdentityVerifier

pytestmark = pytest.mark.integration

ISSUER = "https://idp.test/realms/knowledgeos"

# Test-only routes exercising the dependencies with real data.
probe = APIRouter()


@probe.get("/v1/organizations/{org_id}/_probe")
async def probe_context(org_id: uuid.UUID, ctx: OrgContext) -> dict[str, object]:
    return {"role": ctx.role, "tokens": principal_tokens(ctx)}


@probe.get("/v1/organizations/{org_id}/_manage")
async def probe_permission(
    org_id: uuid.UUID,
    ctx: Annotated[RequestContext, require_permission(Permission.MEMBERS_MANAGE)],
) -> dict[str, str]:
    return {"ok": str(ctx.organization_id)}


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
    application.include_router(probe)
    verifier = FakeIdentityVerifier(
        {
            name: VerifiedToken(issuer=ISSUER, subject=f"{name}-sub", email=f"{name}@x.test")
            for name in ("alice", "carol", "mallory")
        }
    )
    application.dependency_overrides[get_identity_verifier] = lambda: verifier
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def api(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def auth(name: str, org: uuid.UUID | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {name}"}
    if org:
        headers["X-Organization-Id"] = str(org)
    return headers


async def _user_id(api: AsyncClient, name: str) -> uuid.UUID:
    return uuid.UUID((await api.get("/v1/me", headers=auth(name))).json()["user"]["id"])


async def _org(admin: asyncpg.Connection, slug: str) -> uuid.UUID:
    return await admin.fetchval(  # type: ignore[no-any-return]
        "INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3) RETURNING id",
        uuid.uuid4(),
        slug.title(),
        slug,
    )


async def _join(
    admin: asyncpg.Connection, org: uuid.UUID, user: uuid.UUID, role: SystemRole
) -> None:
    await admin.execute(
        "INSERT INTO memberships (id, organization_id, user_id, role_id) VALUES ($1, $2, $3, $4)",
        uuid.uuid4(),
        org,
        user,
        system_role_id(role),
    )


@pytest.fixture
async def world(api: AsyncClient, admin: asyncpg.Connection) -> dict[str, uuid.UUID]:
    """Acme: alice (admin, in group HR). Globex: carol (member). mallory: no memberships."""
    alice, carol = await _user_id(api, "alice"), await _user_id(api, "carol")
    await _user_id(api, "mallory")
    acme, globex = await _org(admin, "acme"), await _org(admin, "globex")
    await _join(admin, acme, alice, SystemRole.ADMIN)
    await _join(admin, globex, carol, SystemRole.MEMBER)
    hr = await admin.fetchval(
        "INSERT INTO groups (id, organization_id, name) VALUES ($1, $2, 'HR') RETURNING id",
        uuid.uuid4(),
        acme,
    )
    await admin.execute(
        "INSERT INTO group_memberships (group_id, user_id, organization_id) VALUES ($1, $2, $3)",
        hr,
        alice,
        acme,
    )
    return {"alice": alice, "carol": carol, "acme": acme, "globex": globex, "hr": hr}


async def test_member_reaches_org_routes_by_path_and_header(
    api: AsyncClient, world: dict[str, uuid.UUID]
) -> None:
    acme = world["acme"]
    by_path = await api.get(f"/v1/organizations/{acme}/members", headers=auth("alice"))
    assert by_path.status_code == 200
    # Header-scoped routes resolve the same context.
    assert (await api.get("/v1/knowledge-bases", headers=auth("alice", acme))).status_code == 200


async def test_other_orgs_routes_are_404_not_403(
    api: AsyncClient, world: dict[str, uuid.UUID]
) -> None:
    globex = world["globex"]
    by_path = await api.get(f"/v1/organizations/{globex}/members", headers=auth("alice"))
    by_header = await api.get("/v1/knowledge-bases", headers=auth("alice", globex))
    nonexistent = await api.get(f"/v1/organizations/{uuid.uuid4()}/members", headers=auth("alice"))

    for response in (by_path, by_header, nonexistent):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"
    # Existing-but-foreign and nonexistent orgs are indistinguishable.
    assert by_path.json()["error"]["message"] == nonexistent.json()["error"]["message"]


async def test_user_without_memberships_sees_no_org(
    api: AsyncClient, world: dict[str, uuid.UUID]
) -> None:
    for org in (world["acme"], world["globex"]):
        response = await api.get(f"/v1/organizations/{org}/_probe", headers=auth("mallory"))
        assert response.status_code == 404


async def test_suspended_member_or_org_is_404(
    api: AsyncClient, admin: asyncpg.Connection, world: dict[str, uuid.UUID]
) -> None:
    url = f"/v1/organizations/{world['acme']}/_probe"
    await admin.execute(
        "UPDATE memberships SET status = 'suspended' WHERE user_id = $1", world["alice"]
    )
    assert (await api.get(url, headers=auth("alice"))).status_code == 404

    await admin.execute(
        "UPDATE memberships SET status = 'active' WHERE user_id = $1", world["alice"]
    )
    await admin.execute(
        "UPDATE organizations SET status = 'suspended' WHERE id = $1", world["acme"]
    )
    assert (await api.get(url, headers=auth("alice"))).status_code == 404


async def test_header_is_required_and_validated(
    api: AsyncClient, world: dict[str, uuid.UUID]
) -> None:
    missing = await api.get("/v1/knowledge-bases", headers=auth("alice"))
    malformed = await api.get(
        "/v1/knowledge-bases", headers={**auth("alice"), "X-Organization-Id": "not-a-uuid"}
    )
    assert missing.status_code == 422
    assert malformed.status_code == 422
    assert "not-a-uuid" not in malformed.text


async def test_context_carries_role_and_principal_tokens(
    api: AsyncClient, world: dict[str, uuid.UUID]
) -> None:
    body = (
        await api.get(f"/v1/organizations/{world['acme']}/_probe", headers=auth("alice"))
    ).json()

    assert body["role"] == "admin"
    assert body["tokens"] == sorted(
        [
            f"user:{world['alice']}",
            f"group:{world['hr']}",
            "role:admin",
            f"org:{world['acme']}",
        ]
    )


async def test_require_permission_is_403_for_members_without_it(
    api: AsyncClient, admin: asyncpg.Connection, world: dict[str, uuid.UUID]
) -> None:
    acme = world["acme"]
    allowed = await api.get(f"/v1/organizations/{acme}/_manage", headers=auth("alice"))
    assert allowed.status_code == 200

    await admin.execute(
        "UPDATE memberships SET role_id = $1 WHERE user_id = $2",
        system_role_id(SystemRole.MEMBER),
        world["alice"],
    )
    denied = await api.get(f"/v1/organizations/{acme}/_manage", headers=auth("alice"))
    assert denied.status_code == 403
    assert denied.json()["error"]["details"] == {"permission": "members.manage"}

    # Another org's members still get 404 first, never 403.
    foreign = await api.get(f"/v1/organizations/{acme}/_manage", headers=auth("carol"))
    assert foreign.status_code == 404
