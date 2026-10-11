"""OpenAPI customisation: publish schemas FastAPI can't infer from routes (SSE event payloads)."""

from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from app.domain.schemas.retrieval import StreamEvent

# Models that are part of the contract but never appear as a JSON request/response body.
EXTRA_SCHEMAS: tuple[type[BaseModel], ...] = (StreamEvent,)

STREAM_EVENT_REF = "#/components/schemas/StreamEvent"


def install_openapi(app: FastAPI) -> None:
    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
        )
        _, defs = models_json_schema(
            [(model, "serialization") for model in EXTRA_SCHEMAS],
            ref_template="#/components/schemas/{model}",
        )
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for name, definition in defs.get("$defs", {}).items():
            components.setdefault(name, definition)
        app.openapi_schema = schema
        return schema

    app.openapi = openapi  # type: ignore[method-assign]
