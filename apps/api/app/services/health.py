"""Readiness checks for the API's hard dependencies (database, Redis, object storage)."""

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
