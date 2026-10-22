"""Atomic per-provider/account RPM + TPM token buckets and UTC RPD cap.

Reserves prompt + maximum completion tokens for EVERY attempt. No refunds (conservative on
failure/cancellation); keys contain only a hash of a caller-configured quota group, no secrets
or source/tenant data. All processes sharing an account must use the same quota group/limits.
Redis failure is fail-closed, never an in-memory or provider fallback.
"""

import asyncio
import hashlib
from dataclasses import dataclass

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.providers.llm.base import LLMRateLimitedError


class ThrottleUnavailableError(RuntimeError):
    """Quota state cannot be verified. No provider may be called."""


@dataclass(frozen=True)
class ProviderLimits:
    requests_per_minute: int
    tokens_per_minute: int
    requests_per_day: int

    def __post_init__(self) -> None:
        if any(
            type(v) is not int or not 1 <= v <= 10**9
            for v in (
                self.requests_per_minute,
                self.tokens_per_minute,
                self.requests_per_day,
            )
        ):
            raise ValueError("provider limits must be positive bounded integers")


# Redis TIME prevents host clock skew. One key, one atomic decision, bounded constant work.
# Redis Lua numbers are doubles; millisecond timestamps and counters stay below 2**53.
_RESERVE = """
local rpm, tpm = tonumber(ARGV[1]), tonumber(ARGV[2])
local rpd, cost = tonumber(ARGV[3]), tonumber(ARGV[4])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local day = math.floor(now / 86400000)
local state = redis.call('HMGET', KEYS[1], 'time', 'requests', 'tokens', 'day', 'daily')
local elapsed = math.max(0, now - (tonumber(state[1]) or now))
local requests = math.min(rpm, (tonumber(state[2]) or rpm) + elapsed * rpm / 60000)
local tokens = math.min(tpm, (tonumber(state[3]) or tpm) + elapsed * tpm / 60000)
local daily = tonumber(state[5]) or 0
if tonumber(state[4]) ~= day then daily = 0 end
local wait = math.max(0, (1 - requests) * 60000 / rpm, (cost - tokens) * 60000 / tpm)
if daily >= rpd then wait = math.max(wait, (day + 1) * 86400000 - now) end
if wait > 0 then return math.ceil(wait) end
redis.call('HSET', KEYS[1], 'time', now, 'requests', requests - 1,
           'tokens', tokens - cost, 'day', day, 'daily', daily + 1)
redis.call('PEXPIRE', KEYS[1], 172800000)
return 0
"""


class RedisProviderThrottle:
    def __init__(self, redis: Redis, *, namespace: str = "kos:llm:v1") -> None:
        if not namespace or len(namespace) > 80 or not namespace.isascii():
            raise ValueError("invalid throttle namespace")
        self._redis, self._namespace = redis, namespace

    def key(self, quota_group: str) -> str:
        if not quota_group or len(quota_group) > 200:
            raise ValueError("invalid provider quota group")
        return self._namespace + ":" + hashlib.sha256(quota_group.encode()).hexdigest()

    async def reserve(self, quota_group: str, tokens: int, limits: ProviderLimits) -> None:
        if type(tokens) is not int or tokens < 1:
            raise ValueError("a positive token reservation is required")
        if tokens > limits.tokens_per_minute:
            raise LLMRateLimitedError("Request exceeds the provider token capacity.")
        try:
            async with asyncio.timeout(2):
                raw = await self._redis.eval(
                    _RESERVE,
                    1,
                    self.key(quota_group),
                    limits.requests_per_minute,
                    limits.tokens_per_minute,
                    limits.requests_per_day,
                    tokens,
                )
        except (RedisError, TimeoutError):
            raise ThrottleUnavailableError("Generation quota state is unavailable.") from None
        if type(raw) is not int or raw < 0:
            raise ThrottleUnavailableError("Invalid generation quota state.")
        if raw:
            raise LLMRateLimitedError(
                "Generation provider quota exhausted.", retry_after_seconds=raw / 1000
            )
