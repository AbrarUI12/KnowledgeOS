"""Policy-allowlisted, deadline-bounded retry/fallback for text-only LLM providers.

No authorization/configuration/cancellation failures degrade. Retry-After is a minimum, never
clamped to an earlier retry; if it exceeds the wait/deadline budget, try only allowed fallbacks.
Once a stream emits ANY chunk, errors propagate without replay or splicing another answer.
"""

import asyncio
import math
import random
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Protocol

from app.providers.llm.base import (
    ChatMessage,
    GenerationParams,
    LLMChunk,
    LLMProvider,
    LLMRateLimitedError,
    LLMResult,
    LLMUnavailableError,
)
from app.providers.llm.validation import validate_request
from app.rag.generation.prompt import MessageTokenCounter
from app.rag.generation.throttle import ProviderLimits


class ProviderThrottle(Protocol):
    async def reserve(self, quota_group: str, tokens: int, limits: ProviderLimits) -> None: ...


@dataclass(frozen=True)
class ProviderTarget:
    provider: LLMProvider
    quota_group: str
    limits: ProviderLimits
    count_tokens: MessageTokenCounter


@dataclass(frozen=True)
class GenerationPolicy:
    allowed_models: frozenset[tuple[str, str]]
    allow_external: bool = False
    local_only: bool = False

    def permits(self, provider: LLMProvider) -> bool:
        return (provider.provider_id, provider.model_id) in self.allowed_models and (
            not provider.is_external or (self.allow_external and not self.local_only)
        )


@dataclass(frozen=True)
class RetryPolicy:
    attempts_per_provider: int = 2
    max_retry_wait_seconds: float = 10
    backoff_seconds: float = 0.5

    def __post_init__(self) -> None:
        if not 1 <= self.attempts_per_provider <= 4 or any(
            not math.isfinite(v) or not 0 <= v <= 60
            for v in (self.max_retry_wait_seconds, self.backoff_seconds)
        ):
            raise ValueError("invalid bounded generation retry policy")


DEFAULT_RETRY = RetryPolicy()


@asynccontextmanager
async def _closing(stream: AsyncIterator[LLMChunk]) -> AsyncIterator[AsyncIterator[LLMChunk]]:
    try:
        yield stream
    finally:
        close = getattr(stream, "aclose", None)
        if close is not None:
            await close()


class LLMGateway:
    def __init__(
        self,
        *,
        primary: ProviderTarget,
        fallbacks: Sequence[ProviderTarget] = (),
        policy: GenerationPolicy,
        throttle: ProviderThrottle,
        retry: RetryPolicy = DEFAULT_RETRY,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        on_selected: Callable[[str, str], None] | None = None,
    ) -> None:
        if len(fallbacks) > 3:
            raise ValueError("at most three generation fallbacks are allowed")
        self._targets = (primary, *fallbacks)
        self._policy, self._throttle = policy, throttle
        self._retry, self._sleep, self._on_selected = retry, sleep, on_selected

    @property
    def provider_id(self) -> str:
        return self._targets[0].provider.provider_id

    @property
    def model_id(self) -> str:
        return self._targets[0].provider.model_id

    @property
    def is_external(self) -> bool:
        # Conservatively describe all possible calls, not just the preferred provider.
        return any(
            t.provider.is_external and self._policy.permits(t.provider) for t in self._targets
        )

    def _prepare(
        self, messages: Sequence[ChatMessage], params: GenerationParams
    ) -> tuple[tuple[ProviderTarget, int], ...]:
        validate_request(messages, params)
        if not self._policy.permits(self._targets[0].provider):
            raise PermissionError("Primary generation model denied by policy.")
        allowed = tuple(t for t in self._targets if self._policy.permits(t.provider))
        reservations = []
        for target in allowed:
            count = target.count_tokens(messages)
            if type(count) is not int or count < 0:
                raise ValueError("invalid generation token count")
            reservations.append((target, count + params.max_output_tokens))
        return tuple(reservations)

    async def _wait(self, error: Exception, attempt: int, deadline: float) -> bool:
        jitter = random.SystemRandom().uniform(0, self._retry.backoff_seconds * 2**attempt)
        delay = jitter
        if isinstance(error, LLMRateLimitedError):
            minimum = error.retry_after_seconds
            if minimum is None or not math.isfinite(minimum) or minimum < 0:
                return False  # unknown cooldown/capacity: do not hammer the same provider
            delay = minimum + jitter
        if (
            delay > self._retry.max_retry_wait_seconds
            or delay >= deadline - asyncio.get_running_loop().time()
        ):
            return False
        await self._sleep(delay)
        return True

    def _remaining(self, params: GenerationParams, deadline: float) -> GenerationParams:
        seconds = deadline - asyncio.get_running_loop().time()
        if seconds <= 0:
            raise TimeoutError
        return params.model_copy(update={"timeout_seconds": seconds})

    async def generate(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> LLMResult:
        messages = tuple(m.model_copy(deep=True) for m in messages)
        params = params or GenerationParams()
        targets = self._prepare(messages, params)
        deadline = asyncio.get_running_loop().time() + params.timeout_seconds
        last: Exception = LLMUnavailableError("No generation provider completed.")
        try:
            async with asyncio.timeout(params.timeout_seconds):
                for target, tokens in targets:
                    for attempt in range(self._retry.attempts_per_provider):
                        try:
                            await self._throttle.reserve(target.quota_group, tokens, target.limits)
                            result = await target.provider.generate(
                                messages, self._remaining(params, deadline)
                            )
                            if (result.provider, result.model) != (
                                target.provider.provider_id,
                                target.provider.model_id,
                            ):
                                raise LLMUnavailableError(
                                    "Unexpected generation provider identity."
                                )
                            if self._on_selected:
                                self._on_selected(result.provider, result.model)
                            return result
                        except (LLMRateLimitedError, LLMUnavailableError) as exc:
                            last = exc
                            if (
                                attempt + 1 == self._retry.attempts_per_provider
                                or not await self._wait(exc, attempt, deadline)
                            ):
                                break
        except TimeoutError:
            raise LLMUnavailableError("Generation gateway deadline exceeded.") from None
        raise last

    async def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> AsyncGenerator[LLMChunk, None]:
        # Chunk contract has no provider/model fields: use a request-scoped on_selected callback
        # to record the actual streamed identity. Never store per-call state on a shared gateway.
        messages = tuple(m.model_copy(deep=True) for m in messages)
        params = params or GenerationParams()
        targets = self._prepare(messages, params)
        deadline = asyncio.get_running_loop().time() + params.timeout_seconds
        last: Exception = LLMUnavailableError("No generation provider completed.")
        try:
            async with asyncio.timeout(params.timeout_seconds):
                for target, tokens in targets:
                    for attempt in range(self._retry.attempts_per_provider):
                        emitted = False
                        try:
                            await self._throttle.reserve(target.quota_group, tokens, target.limits)
                            async with _closing(
                                target.provider.stream(messages, self._remaining(params, deadline))
                            ) as stream:
                                async for chunk in stream:
                                    if not emitted and self._on_selected:
                                        self._on_selected(
                                            target.provider.provider_id, target.provider.model_id
                                        )
                                    emitted = True
                                    yield chunk
                            if not emitted:
                                raise LLMUnavailableError("Generation stream was empty.")
                            return
                        except (LLMRateLimitedError, LLMUnavailableError) as exc:
                            if emitted:
                                raise
                            last = exc
                            if (
                                attempt + 1 == self._retry.attempts_per_provider
                                or not await self._wait(exc, attempt, deadline)
                            ):
                                break
        except TimeoutError:
            raise LLMUnavailableError("Generation gateway deadline exceeded.") from None
        raise last
