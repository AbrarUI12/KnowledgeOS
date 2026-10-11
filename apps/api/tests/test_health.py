import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app


@pytest.mark.unit
async def test_health_live_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
async def test_ready_is_200_when_all_dependencies_are_up(live_client: AsyncClient) -> None:
    response = await live_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "checks": {"database": "ok", "redis": "ok", "object_storage": "ok"},
    }


@pytest.mark.integration
async def test_ready_is_503_when_database_is_unreachable(migrated_settings: Settings) -> None:
    broken = migrated_settings.model_copy(
        update={
            "database_url": SecretStr(
                "postgresql+asyncpg://knowledgeos_app:wrong@127.0.0.1:1/knowledgeos"
            ),
            "readiness_timeout_seconds": 1.0,
        }
    )
    app = create_app(broken)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["checks"]["database"] == "unavailable"
    assert body["checks"]["redis"] == "ok"
    assert "wrong" not in response.text  # never leak connection details
