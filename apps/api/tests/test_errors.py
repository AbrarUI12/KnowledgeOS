import uuid

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.api.errors import Conflict, NotFound
from app.main import create_app
from tests.support import make_settings


class Payload(BaseModel):
    name: str
    count: int


@pytest.fixture
async def error_client() -> AsyncClient:
    app: FastAPI = create_app(make_settings())

    @app.get("/boom/not-found")
    async def not_found() -> None:
        raise NotFound("Document not found.")

    @app.get("/boom/conflict")
    async def conflict() -> None:
        raise Conflict(details={"field": "slug"})

    @app.get("/boom/crash")
    async def crash() -> None:
        raise RuntimeError("database password=hunter2 leaked in message")

    @app.post("/boom/validate")
    async def validate(payload: Payload) -> Payload:
        return payload

    # raise_app_exceptions=False: let the app's own 500 handler build the response.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    return AsyncClient(transport=transport, base_url="http://test")


def assert_envelope(body: dict[str, object], code: str) -> dict[str, object]:
    assert set(body) == {"error"}
    error = body["error"]
    assert isinstance(error, dict)
    assert set(error) == {"code", "message", "request_id", "details"}
    assert error["code"] == code
    uuid.UUID(str(error["request_id"]))
    return error


@pytest.mark.unit
async def test_app_error_uses_envelope(error_client: AsyncClient) -> None:
    response = await error_client.get("/boom/not-found")

    assert response.status_code == 404
    error = assert_envelope(response.json(), "not_found")
    assert error["message"] == "Document not found."
    assert response.headers["x-request-id"] == error["request_id"]


@pytest.mark.unit
async def test_app_error_details(error_client: AsyncClient) -> None:
    response = await error_client.get("/boom/conflict")

    assert response.status_code == 409
    assert assert_envelope(response.json(), "conflict")["details"] == {"field": "slug"}


@pytest.mark.unit
async def test_unknown_route_is_404_envelope(client: AsyncClient) -> None:
    response = await client.get("/does-not-exist")

    assert response.status_code == 404
    assert_envelope(response.json(), "not_found")


@pytest.mark.unit
async def test_validation_error_does_not_echo_input(error_client: AsyncClient) -> None:
    response = await error_client.post(
        "/boom/validate", json={"name": "s3cr3t-value", "count": "not-a-number"}
    )

    assert response.status_code == 422
    error = assert_envelope(response.json(), "validation_failed")
    details = error["details"]
    assert isinstance(details, dict)
    assert details["errors"][0]["loc"] == ["body", "count"]
    assert "s3cr3t-value" not in response.text
    assert "not-a-number" not in response.text


@pytest.mark.unit
async def test_unhandled_error_is_safe_500(error_client: AsyncClient) -> None:
    response = await error_client.get("/boom/crash")

    assert response.status_code == 500
    error = assert_envelope(response.json(), "internal_error")
    assert error["message"] == "An unexpected error occurred."
    assert "hunter2" not in response.text
    assert response.headers["x-request-id"] == error["request_id"]
