"""`GET /v1/me` and the authentication dependency against real PostgreSQL (T1.1)."""

import uuid
from collections.abc import AsyncIterator

import asyncpg
import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.dependencies.auth import get_identity_verifier
from app.auth.permissions import SYSTEM_ROLE_PERMISSIONS, SystemRole, system_role_id
from app.core.config import Settings
from app.main import create_app
from app.providers.identity.base import IdentityProviderUnavailableError, VerifiedToken
from tests.fakes import FakeIdentityVerifier

pytestmark = pytest.mark.integration

ISSUER = "https://idp.test/realms/knowledgeos"


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def owner(migrated_settings: Settings) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(_dsn(migrated_settings.database_migration_url.get_secret_value()))
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
def verifier() -> FakeIdentityVerifier:
    tokens = {
        "alice-token": VerifiedToken(
            issuer=ISSUER, subject="alice-sub", email="alice@acme.test", name="Alice"
        ),
        "bob-token": VerifiedToken(issuer=ISSUER, subject="bob-sub", email="bob@acme.test"),
    }
    return FakeIdentityVerifier(tokens)


@pytest.fixture
async def api(
    migrated_settings: Settings, verifier: FakeIdentityVerifier, owner: asyncpg.Connection
) -> AsyncIterator[AsyncClient]:
    app = create_app(migrated_settings)
    app.dependency_overrides[get_identity_verifier] = lambda: verifier
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield client


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_missing_token_is_401_with_bearer_challenge(api: AsyncClient) -> None:
    response = await api.get("/v1/me")

    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json()["error"]["code"] == "unauthorized"


async def test_wrong_scheme_and_invalid_token_are_401(api: AsyncClient) -> None:
    assert (await api.get("/v1/me", headers={"Authorization": "Basic abc"})).status_code == 401
    response = await api.get("/v1/me", headers=auth("forged"))
    assert response.status_code == 401
    assert "forged" not in response.text


async def test_first_request_provisions_the_user_exactly_once(
    api: AsyncClient, owner: asyncpg.Connection
) -> None:
    first = await api.get("/v1/me", headers=auth("alice-token"))
    second = await api.get("/v1/me", headers=auth("alice-token"))

    assert first.status_code == 200
    body = first.json()
    assert body["user"]["email"] == "alice@acme.test"
    assert body["user"]["display_name"] == "Alice"
    assert body["memberships"] == []
    assert second.json()["user"]["id"] == body["user"]["id"]
    count = await owner.fetchval(
        "SELECT count(*) FROM users WHERE issuer = $1 AND external_subject = 'alice-sub'", ISSUER
    )
    assert count == 1


async def test_profile_follows_the_idp_but_keeps_values_when_claims_are_missing(
    api: AsyncClient, verifier: FakeIdentityVerifier
) -> None:
    await api.get("/v1/me", headers=auth("alice-token"))
    verifier.tokens["alice-token"] = VerifiedToken(
        issuer=ISSUER, subject="alice-sub", email="alice@new.test", name=None
    )

    body = (await api.get("/v1/me", headers=auth("alice-token"))).json()

    assert body["user"]["email"] == "alice@new.test"
    assert body["user"]["display_name"] == "Alice"  # name claim missing → old value kept


async def test_memberships_include_role_and_effective_permissions(
    api: AsyncClient, owner: asyncpg.Connection
) -> None:
    user_id = uuid.UUID((await api.get("/v1/me", headers=auth("alice-token"))).json()["user"]["id"])
    org_id = await owner.fetchval(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'acme') RETURNING id",
        uuid.uuid4(),
    )
    await owner.execute(
        "INSERT INTO memberships (id, organization_id, user_id, role_id) VALUES ($1, $2, $3, $4)",
        uuid.uuid4(),
        org_id,
        user_id,
        system_role_id(SystemRole.ADMIN),
    )
    suspended_org = await owner.fetchval(
        "INSERT INTO organizations (id, name, slug, status) "
        "VALUES ($1, 'Old', 'old', 'suspended') RETURNING id",
        uuid.uuid4(),
    )
    await owner.execute(
        "INSERT INTO memberships (id, organization_id, user_id, role_id) VALUES ($1, $2, $3, $4)",
        uuid.uuid4(),
        suspended_org,
        user_id,
        system_role_id(SystemRole.OWNER),
    )

    memberships = (await api.get("/v1/me", headers=auth("alice-token"))).json()["memberships"]

    assert len(memberships) == 1  # suspended org hidden
    assert memberships[0]["organization_slug"] == "acme"
    assert memberships[0]["role"] == "admin"
    assert set(memberships[0]["permissions"]) == {
        p.value for p in SYSTEM_ROLE_PERMISSIONS[SystemRole.ADMIN]
    }


async def test_other_users_memberships_are_not_visible(
    api: AsyncClient, owner: asyncpg.Connection
) -> None:
    alice = uuid.UUID((await api.get("/v1/me", headers=auth("alice-token"))).json()["user"]["id"])
    org = await owner.fetchval(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'acme') RETURNING id",
        uuid.uuid4(),
    )
    await owner.execute(
        "INSERT INTO memberships (id, organization_id, user_id, role_id) VALUES ($1, $2, $3, $4)",
        uuid.uuid4(),
        org,
        alice,
        system_role_id(SystemRole.MEMBER),
    )

    assert (await api.get("/v1/me", headers=auth("bob-token"))).json()["memberships"] == []


async def test_disabled_user_is_403(api: AsyncClient, owner: asyncpg.Connection) -> None:
    await api.get("/v1/me", headers=auth("alice-token"))
    await owner.execute("UPDATE users SET status = 'disabled' WHERE external_subject = 'alice-sub'")

    response = await api.get("/v1/me", headers=auth("alice-token"))

    assert response.status_code == 403


async def test_identity_provider_outage_is_503(
    migrated_settings: Settings, owner: asyncpg.Connection
) -> None:
    class DownVerifier:
        async def verify(self, token: str) -> VerifiedToken:
            raise IdentityProviderUnavailableError("down")

    app = create_app(migrated_settings)
    app.dependency_overrides[get_identity_verifier] = DownVerifier
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/v1/me", headers=auth("any"))

    assert response.status_code == 503


async def test_real_keycloak_token_when_local_stack_is_running(
    migrated_settings: Settings, owner: asyncpg.Connection
) -> None:
    """End-to-end with the real dev Keycloak (`make up`). Skipped when it isn't running (CI)."""
    issuer = "http://localhost:8080/realms/knowledgeos"
    try:
        async with httpx.AsyncClient(timeout=3) as http:
            token_response = await http.post(
                f"{issuer}/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": "knowledgeos-cli",
                    "username": "alice@acme.test",
                    "password": "alice-dev-password",
                    "scope": "openid",
                },
            )
    except httpx.HTTPError:
        pytest.skip("local Keycloak not running")
    if token_response.status_code != 200:
        pytest.skip("local Keycloak realm not available")
    token = token_response.json()["access_token"]

    settings = migrated_settings.model_copy(update={"oidc_issuer": issuer, "oidc_jwks_url": None})
    app = create_app(settings)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/v1/me", headers=auth(token))

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "alice@acme.test"
