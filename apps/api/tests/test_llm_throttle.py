import asyncio
import uuid

import pytest
from redis.asyncio import Redis
from testcontainers.community.redis import RedisContainer

from app.providers.llm.base import LLMRateLimitedError
from app.rag.generation.throttle import ProviderLimits, RedisProviderThrottle

pytestmark = pytest.mark.integration


async def test_real_redis_atomic_quota_reservations_never_overspend(
    redis_container: RedisContainer,
) -> None:
    redis = Redis(
        host=redis_container.get_container_host_ip(),
        port=int(redis_container.get_exposed_port(6379)),
    )
    throttle = RedisProviderThrottle(redis, namespace=f"test:{uuid.uuid4()}")
    limits = ProviderLimits(1000, 1000, 3)
    try:
        outcomes = await asyncio.gather(
            *(throttle.reserve("shared-account", 1, limits) for _ in range(20)),
            return_exceptions=True,
        )
        assert sum(outcome is None for outcome in outcomes) == 3
        denied = [outcome for outcome in outcomes if isinstance(outcome, LLMRateLimitedError)]
        assert len(denied) == 17
        assert all(d.retry_after_seconds is not None and d.retry_after_seconds > 0 for d in denied)
        assert 0 < await redis.pttl(throttle.key("shared-account")) <= 172_800_000
        assert "shared-account" not in throttle.key("shared-account")
        await throttle.reserve("different-account", 1, limits)
    finally:
        await redis.aclose()


async def test_real_redis_token_capacity_rejection_does_not_consume_request_budget(
    redis_container: RedisContainer,
) -> None:
    redis = Redis(
        host=redis_container.get_container_host_ip(),
        port=int(redis_container.get_exposed_port(6379)),
    )
    throttle = RedisProviderThrottle(redis, namespace=f"test:{uuid.uuid4()}")
    limits = ProviderLimits(1, 10, 2)
    try:
        with pytest.raises(LLMRateLimitedError, match="capacity"):
            await throttle.reserve("account", 11, limits)
        assert not await redis.exists(throttle.key("account"))
        await throttle.reserve("account", 10, limits)
        with pytest.raises(LLMRateLimitedError) as exc:
            await throttle.reserve("account", 1, limits)
        assert exc.value.retry_after_seconds is not None
        assert 0 < exc.value.retry_after_seconds <= 60
    finally:
        await redis.aclose()


async def test_real_redis_refills_buckets_and_resets_only_previous_utc_days(
    redis_container: RedisContainer,
) -> None:
    redis = Redis(
        host=redis_container.get_container_host_ip(),
        port=int(redis_container.get_exposed_port(6379)),
    )
    throttle = RedisProviderThrottle(redis, namespace=f"test:{uuid.uuid4()}")
    limits = ProviderLimits(1, 10, 1)
    try:
        await throttle.reserve("account", 10, limits)
        seconds, micros = await redis.time()
        now = seconds * 1000 + micros // 1000
        # Set the TEST account's last successful reservation to yesterday. Redis TIME itself
        # is real; neither the Lua algorithm nor its command results are mocked.
        await redis.hset(
            throttle.key("account"),
            mapping={
                "time": now - 86_400_000,
                "day": now // 86_400_000 - 1,
            },
        )
        await throttle.reserve("account", 10, limits)
        with pytest.raises(LLMRateLimitedError) as exc:
            await throttle.reserve("account", 1, limits)
        assert exc.value.retry_after_seconds is not None
        assert exc.value.retry_after_seconds > 60  # same-day RPD cap still applies
    finally:
        await redis.aclose()
