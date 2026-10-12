"""KnowledgeOS API application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.routing import APIRoute
from redis.asyncio import Redis

from app.api import health
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.openapi import install_openapi
from app.api.v1.router import api_v1_router
from app.core.config import Settings, get_settings
from app.core.email import configure_email_validation
from app.core.logging import configure_logging
from app.core.s3 import create_s3_client
from app.db.session import create_engine, create_sessionmaker
from app.providers.identity.oidc import OIDCVerifier
from app.providers.storage import S3ObjectStore


def _operation_id(route: APIRoute) -> str:
    """Stable OpenAPI operation IDs (tag_function) for frontend client generation."""
    tag = str(route.tags[0]) if route.tags else "default"
    return f"{tag}_{route.name}"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)
    configure_email_validation(settings)

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
        app.state.object_store = S3ObjectStore(
            endpoint_url=settings.s3_endpoint_url,
            public_endpoint_url=settings.s3_public_endpoint_url,
            region_name=settings.s3_region,
            access_key_id=settings.s3_access_key_id.get_secret_value(),
            secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            force_path_style=settings.s3_force_path_style,
            connect_timeout_seconds=settings.s3_connect_timeout_seconds,
            read_timeout_seconds=settings.s3_read_timeout_seconds,
            max_attempts=settings.s3_max_attempts,
        )
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
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health.router)
    app.include_router(api_v1_router)
    install_openapi(app)
    return app


app = create_app()
