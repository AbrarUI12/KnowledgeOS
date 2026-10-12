"""KnowledgeOS API application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from redis.asyncio import Redis

from app.api import health
from app.api.errors import UnhandledErrorMiddleware, register_exception_handlers
from app.api.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from app.api.openapi import install_openapi
from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.s3 import create_s3_client
from app.db.session import create_engine, create_sessionmaker
from app.domain.schemas.common import ORG_HEADER
from app.providers.identity.oidc import OIDCVerifier


def _operation_id(route: APIRoute) -> str:
    """Stable OpenAPI operation IDs (tag_function) for frontend client generation."""
    tag = str(route.tags[0]) if route.tags else "default"
    return f"{tag}_{route.name}"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        redis = Redis.from_url(
            settings.redis_url.get_secret_value(),
            socket_connect_timeout=settings.readiness_timeout_seconds,
            socket_timeout=settings.readiness_timeout_seconds,
        )
        app.state.settings = settings
        app.state.engine = engine
        app.state.sessionmaker = create_sessionmaker(engine)
        app.state.redis = redis
        app.state.s3 = create_s3_client(settings)
        http = httpx.AsyncClient(timeout=settings.oidc_http_timeout_seconds)
        app.state.identity_verifier = OIDCVerifier(settings, http)
        try:
            yield
        finally:
            await http.aclose()
            await redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
    )
    app.add_middleware(UnhandledErrorMiddleware)  # innermost of the three
    app.add_middleware(RequestContextMiddleware)
    # Added last = outermost, so preflights and error responses also carry CORS headers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.web_origin_list,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            ORG_HEADER,
            "Idempotency-Key",
            REQUEST_ID_HEADER,
        ],
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
        max_age=600,
    )
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_v1_router)
    install_openapi(app)
    return app


app = create_app()
