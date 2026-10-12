"""Readiness checks for the API's hard dependencies (database, Redis, object storage) and the
runtime database role's safety (it must be subject to row-level security)."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal

import structlog
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.config import Settings
from app.core.s3 import S3Client

logger = structlog.get_logger(__name__)

CheckStatus = Literal["ok", "unavailable"]


class ReadinessReport(BaseModel):
    status: CheckStatus
    checks: dict[str, CheckStatus]


async def _database(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))


# The runtime role must not be a superuser, must not have BYPASSRLS and must own no tables in the
# schema (owners skip non-forced RLS and could ALTER the policies away). Plan §8.2, ADR-004.
_ROLE_CHECK = text(
    """
    SELECT r.rolsuper OR r.rolbypassrls
           OR EXISTS (
             SELECT 1 FROM pg_class c
             WHERE c.relowner = r.oid AND c.relnamespace = 'public'::regnamespace
           ) AS unsafe
    FROM pg_roles r WHERE r.rolname = current_user
    """
)


class UnsafeDatabaseRole(RuntimeError):
    """The API connects with a role that can bypass row-level security."""


async def _database_role(engine: AsyncEngine) -> None:
    async with engine.connect() as conn:
        if (await conn.execute(_ROLE_CHECK)).scalar_one():
            raise UnsafeDatabaseRole


async def _redis(redis: Redis) -> None:
    await redis.ping()


async def _object_storage(s3: S3Client, buckets: tuple[str, ...]) -> None:
    for bucket in buckets:
        await asyncio.to_thread(s3.head_bucket, Bucket=bucket)


async def check_readiness(
    *, settings: Settings, engine: AsyncEngine, redis: Redis, s3: S3Client
) -> ReadinessReport:
    checks: dict[str, Callable[[], Awaitable[None]]] = {
        "database": lambda: _database(engine),
        "database_role": lambda: _database_role(engine),
        "redis": lambda: _redis(redis),
        "object_storage": lambda: _object_storage(s3, settings.s3_buckets),
    }

    async def run(name: str, check: Callable[[], Awaitable[None]]) -> CheckStatus:
        try:
            await asyncio.wait_for(check(), timeout=settings.readiness_timeout_seconds)
            return "ok"
        except Exception as exc:
            # Log the type only: connection errors can embed DSNs/hosts.
            logger.warning("readiness_check_failed", check=name, error_type=type(exc).__name__)
            return "unavailable"

    names = list(checks)
    results = await asyncio.gather(*(run(n, checks[n]) for n in names))
    report = dict(zip(names, results, strict=True))
    overall: CheckStatus = "ok" if all(r == "ok" for r in results) else "unavailable"
    return ReadinessReport(status=overall, checks=report)
