import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.unit
async def test_generates_request_id_when_missing(client: AsyncClient) -> None:
    response = await client.get("/health/live")

    uuid.UUID(response.headers["x-request-id"])


@pytest.mark.unit
async def test_propagates_valid_incoming_request_id(client: AsyncClient) -> None:
    incoming = str(uuid.uuid4())

    response = await client.get("/health/live", headers={"X-Request-ID": incoming})

    assert response.headers["x-request-id"] == incoming


@pytest.mark.unit
async def test_replaces_invalid_incoming_request_id(client: AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "<script>alert(1)"})

    returned = response.headers["x-request-id"]
    assert returned != "<script>alert(1)"
    uuid.UUID(returned)
