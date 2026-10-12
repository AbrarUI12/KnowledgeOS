"""CORS for the browser client (issue #18): exact origins, bearer headers, no credentials."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from tests.support import make_settings

pytestmark = pytest.mark.unit

ALLOWED = "http://localhost:3100"


def client(**settings: object) -> AsyncClient:
    app = create_app(make_settings(**settings))
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_preflight_allows_listed_origin_and_api_headers() -> None:
    async with client() as c:
        response = await c.options(
            "/v1/knowledge-bases",
            headers={
                "Origin": ALLOWED,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "authorization,content-type,x-organization-id,idempotency-key"
                ),
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED
    allowed_headers = response.headers["access-control-allow-headers"].lower()
    for header in ("authorization", "content-type", "x-organization-id", "idempotency-key"):
        assert header in allowed_headers
    assert "access-control-allow-credentials" not in response.headers


async def test_unlisted_origin_gets_no_cors_headers() -> None:
    async with client() as c:
        preflight = await c.options(
            "/v1/me",
            headers={"Origin": "https://evil.test", "Access-Control-Request-Method": "GET"},
        )
        simple = await c.get("/health/live", headers={"Origin": "https://evil.test"})
    assert preflight.status_code == 400
    assert "access-control-allow-origin" not in simple.headers


async def test_error_responses_carry_cors_and_expose_request_id() -> None:
    async with client() as c:
        response = await c.get("/v1/me", headers={"Origin": ALLOWED})
    assert response.status_code >= 400  # 401 once T1.1 merges; 501 stub on main today
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert "x-request-id" in response.headers["access-control-expose-headers"].lower()


@pytest.mark.parametrize(
    "value",
    [
        "*",
        "localhost:3000",
        "https://*.example.com",
        "https://web.test/app",
        "https://web.test/?x=1",
        "https://user:pw@web.test",
        "https://web.test#frag",
        "ftp://web.test",
    ],
)
def test_wildcards_and_bare_hosts_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="exact"):
        create_app(make_settings(web_origins=value))


def test_trailing_slash_origin_is_normalized() -> None:
    assert make_settings(web_origins="https://web.test/").web_origin_list == ["https://web.test"]


async def test_unhandled_500_carries_cors_and_request_id() -> None:
    """Review #20 (MEDIUM): crashes must still be readable by the browser."""
    app = create_app(make_settings())

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret detail")

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        response = await c.get("/boom", headers={"Origin": ALLOWED})

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "secret detail" not in response.text
    assert response.headers["access-control-allow-origin"] == ALLOWED
    assert response.headers["x-request-id"]
