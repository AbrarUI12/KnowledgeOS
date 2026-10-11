"""Shared test fixtures.

Unit tests use `client` (no external services, no lifespan).
Integration tests use `integration_settings` / `live_client`, backed by real containers started once
per session via Testcontainers. The Postgres container mounts the same init scripts as Docker
Compose, so roles (owner/app/dispatcher) and extensions match local development exactly.
"""

from collections.abc import AsyncIterator, Iterator

import boto3
import pytest
from alembic import command
from botocore.config import Config as BotoConfig
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr
from testcontainers.community.minio import MinioContainer
from testcontainers.community.postgres import PostgresContainer
from testcontainers.community.redis import RedisContainer

from app.core.config import Settings
from app.main import create_app
from tests.support import REPO_ROOT, alembic_config, make_settings

PG_INIT_DIR = REPO_ROOT / "infra" / "docker" / "postgres" / "init"

PG_IMAGE = "pgvector/pgvector:pg17"
REDIS_IMAGE = "redis:7-alpine"
MINIO_IMAGE = "pgsty/minio:RELEASE.2026-08-04T00-00-00Z"
OWNER_PW, APP_PW, DISPATCHER_PW = "owner_test_pw", "app_test_pw", "dispatcher_test_pw"
S3_KEY, S3_SECRET = "kos_test", "kos_test_secret"
BUCKETS = ("kos-quarantine", "kos-trusted", "kos-artifacts")


# --------------------------------------------------------------------------- unit fixtures


@pytest.fixture
def app() -> FastAPI:
    return create_app(make_settings())


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


# --------------------------------------------------------------------------- containers


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    container = (
        PostgresContainer(PG_IMAGE, username="postgres", password="postgres", dbname="knowledgeos")
        .with_volume_mapping(str(PG_INIT_DIR), "/docker-entrypoint-initdb.d", "ro")
        .with_env("KOS_OWNER_PASSWORD", OWNER_PW)
        .with_env("KOS_APP_PASSWORD", APP_PW)
        .with_env("KOS_DISPATCHER_PASSWORD", DISPATCHER_PW)
        .with_env("KEYCLOAK_DB_PASSWORD", "unused")
    )
    with container:
        yield container


@pytest.fixture(scope="session")
def redis_container() -> Iterator[RedisContainer]:
    with RedisContainer(REDIS_IMAGE) as container:
        yield container


@pytest.fixture(scope="session")
def minio_container() -> Iterator[MinioContainer]:
    with MinioContainer(MINIO_IMAGE, access_key=S3_KEY, secret_key=S3_SECRET) as container:
        yield container


def _pg_url(container: PostgresContainer, user: str, password: str) -> str:
    host = container.get_container_host_ip()
    port = container.get_exposed_port(5432)
    return f"postgresql+asyncpg://{user}:{password}@{host}:{port}/knowledgeos"


@pytest.fixture(scope="session")
def integration_settings(
    postgres_container: PostgresContainer,
    redis_container: RedisContainer,
    minio_container: MinioContainer,
) -> Settings:
    s3_endpoint = (
        f"http://{minio_container.get_container_host_ip()}:{minio_container.get_exposed_port(9000)}"
    )
    s3 = boto3.client(
        "s3",
        endpoint_url=s3_endpoint,
        aws_access_key_id=S3_KEY,
        aws_secret_access_key=S3_SECRET,
        region_name="us-east-1",
        config=BotoConfig(s3={"addressing_style": "path"}),
    )
    for bucket in BUCKETS:
        s3.create_bucket(Bucket=bucket)

    redis_host = redis_container.get_container_host_ip()
    redis_port = redis_container.get_exposed_port(6379)
    return make_settings(
        database_url=SecretStr(_pg_url(postgres_container, "knowledgeos_app", APP_PW)),
        database_migration_url=SecretStr(
            _pg_url(postgres_container, "knowledgeos_owner", OWNER_PW)
        ),
        redis_url=SecretStr(f"redis://{redis_host}:{redis_port}/0"),
        s3_endpoint_url=s3_endpoint,
        s3_public_endpoint_url=s3_endpoint,
        s3_access_key_id=SecretStr(S3_KEY),
        s3_secret_access_key=SecretStr(S3_SECRET),
    )


@pytest.fixture(scope="session")
def admin_dsn(postgres_container: PostgresContainer) -> str:
    """Superuser DSN (asyncpg format) for test setup and cleanup.

    Forced RLS binds the owner role too, so fixtures that insert rows into several organizations,
    or purge everything, connect like a DBA would. Never use it to *verify* isolation: that must
    run as `knowledgeos_app` (docs/TESTING.md).
    """
    return _pg_url(postgres_container, "postgres", "postgres").replace(
        "postgresql+asyncpg://", "postgresql://"
    )


@pytest.fixture(scope="session")
def migrated_settings(integration_settings: Settings) -> Settings:
    command.upgrade(alembic_config(integration_settings), "head")
    return integration_settings


@pytest.fixture
async def live_client(migrated_settings: Settings) -> AsyncIterator[AsyncClient]:
    """Client against an app whose lifespan ran (engine, Redis, S3 all connected to containers)."""
    application = create_app(migrated_settings)
    async with (
        application.router.lifespan_context(application),
        AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as c,
    ):
        yield c
