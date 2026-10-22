import asyncio
from collections.abc import AsyncIterator, Sequence

import pytest
import respx

from app.providers.llm.base import (
    ChatMessage,
    GenerationParams,
    LLMChunk,
    LLMProvider,
    LLMRateLimitedError,
    LLMResult,
    LLMUnavailableError,
)
from app.providers.llm.fake import FakeLLM
from app.providers.llm.openai_compatible import LLMRequestError, OpenAICompatibleLLM
from app.rag.generation.gateway import GenerationPolicy, LLMGateway, ProviderTarget, RetryPolicy
from app.rag.generation.throttle import ProviderLimits, ThrottleUnavailableError
from tests.test_llm_providers import MESSAGES, payload

pytestmark = [pytest.mark.unit, pytest.mark.security]
LIMITS = ProviderLimits(60, 60_000, 1000)


class ThrottleRecorder:
    """Gateway collaborator, NOT a fake implementation of the Redis algorithm under test."""

    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, int, ProviderLimits]] = []
        self.error = error

    async def reserve(self, quota_group: str, tokens: int, limits: ProviderLimits) -> None:
        self.calls.append((quota_group, tokens, limits))
        if self.error:
            raise self.error


class Primary(FakeLLM):
    provider_id = "primary"


class External(FakeLLM):
    provider_id = "external"
    is_external = True


def target(provider: LLMProvider, count: int = 100) -> ProviderTarget:
    return ProviderTarget(provider, provider.provider_id, LIMITS, lambda messages: count)


def policy(
    *providers: LLMProvider, external: bool = False, local: bool = False
) -> GenerationPolicy:
    return GenerationPolicy(
        frozenset((p.provider_id, p.model_id) for p in providers), external, local
    )


@respx.mock
async def test_long_retry_after_falls_back_only_to_allowed_model_and_captures_actual_usage() -> (
    None
):
    primary = OpenAICompatibleLLM(
        base_url="https://primary.test/v1",
        provider_id="primary",
        model_id="pinned-model",
        is_external=True,
    )
    secondary = OpenAICompatibleLLM(
        base_url="https://secondary.test/v1",
        provider_id="secondary",
        model_id="pinned-model",
        is_external=True,
    )
    first = respx.post("https://primary.test/v1/chat/completions").respond(
        429, headers={"Retry-After": "90000"}
    )
    second = respx.post("https://secondary.test/v1/chat/completions").respond(200, json=payload())
    throttle = ThrottleRecorder()
    selected: list[tuple[str, str]] = []
    gateway = LLMGateway(
        primary=target(primary),
        fallbacks=[target(secondary, 200)],
        policy=policy(primary, secondary, external=True),
        throttle=throttle,
        on_selected=lambda p, m: selected.append((p, m)),
    )
    try:
        result = await gateway.generate(MESSAGES)
        assert first.call_count == 1
        assert second.call_count == 1
        assert result.provider == "secondary"
        assert result.usage.input_tokens == 40
        assert selected == [("secondary", "pinned-model")]
        assert [c[1] for c in throttle.calls] == [1124, 1224]  # per-MODEL counter + output cap
    finally:
        await primary.aclose()
        await secondary.aclose()


async def test_retry_after_is_a_minimum_and_jitter_never_makes_retry_earlier() -> None:
    fake = Primary([LLMRateLimitedError("temporary", retry_after_seconds=2), "Supported [S1]"])
    waits: list[float] = []

    async def record_wait(delay: float) -> None:
        waits.append(delay)

    gateway = LLMGateway(
        primary=target(fake), policy=policy(fake), throttle=ThrottleRecorder(), sleep=record_wait
    )
    assert (await gateway.generate(MESSAGES)).text == "Supported [S1]"
    assert len(waits) == 1
    assert 2 <= waits[0] <= 2.5
    assert len(fake.calls) == 2


@pytest.mark.parametrize("error", [PermissionError("denied"), LLMRequestError("bad request")])
async def test_authorization_and_permanent_request_errors_never_retry_or_fallback(
    error: Exception,
) -> None:
    primary, secondary = Primary([error]), External(["MUST NOT CALL"])
    gateway = LLMGateway(
        primary=target(primary),
        fallbacks=[target(secondary)],
        policy=policy(primary, secondary, external=True),
        throttle=ThrottleRecorder(),
    )
    with pytest.raises(type(error)):
        await gateway.generate(MESSAGES)
    assert len(primary.calls) == 1
    assert secondary.calls == []


async def test_denied_primary_and_local_only_fail_closed_before_external_calls() -> None:
    primary, external = Primary([LLMUnavailableError("down")]), External(["MUST NOT CALL"])
    throttle = ThrottleRecorder()
    denied = LLMGateway(primary=target(primary), policy=policy(external), throttle=throttle)
    with pytest.raises(PermissionError):
        await denied.generate(MESSAGES)
    assert throttle.calls == []
    assert primary.calls == []
    local = LLMGateway(
        primary=target(primary),
        fallbacks=[target(external)],
        policy=policy(primary, external, external=True, local=True),
        throttle=throttle,
        retry=RetryPolicy(attempts_per_provider=1),
    )
    with pytest.raises(LLMUnavailableError):
        await local.generate(MESSAGES)
    assert not local.is_external
    assert external.calls == []


async def test_transient_retries_are_bounded_before_allowed_fallback() -> None:
    primary = Primary([LLMUnavailableError("down"), LLMUnavailableError("still down")])
    secondary = FakeLLM(["Supported [S1]"])
    gateway = LLMGateway(
        primary=target(primary),
        fallbacks=[target(secondary)],
        policy=policy(primary, secondary),
        throttle=ThrottleRecorder(),
        retry=RetryPolicy(backoff_seconds=0),
    )
    assert (await gateway.generate(MESSAGES)).provider == "fake"
    assert len(primary.calls) == 2
    assert len(secondary.calls) == 1


async def test_unavailable_quota_state_is_fail_closed_even_with_allowed_fallback() -> None:
    primary, secondary = Primary(["MUST NOT CALL"]), FakeLLM(["MUST NOT CALL"])
    gateway = LLMGateway(
        primary=target(primary),
        fallbacks=[target(secondary)],
        policy=policy(primary, secondary),
        throttle=ThrottleRecorder(ThrottleUnavailableError("redis down")),
    )
    with pytest.raises(ThrottleUnavailableError):
        await gateway.generate(MESSAGES)
    assert primary.calls == []
    assert secondary.calls == []


class PartialFailure(Primary):
    async def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> AsyncIterator[LLMChunk]:
        yield LLMChunk(delta="Partial answer")
        raise LLMUnavailableError("connection lost")


async def test_stream_never_retries_or_splices_a_fallback_after_output() -> None:
    primary, secondary = PartialFailure([]), FakeLLM(["MUST NOT CALL"])
    throttle = ThrottleRecorder()
    gateway = LLMGateway(
        primary=target(primary),
        fallbacks=[target(secondary)],
        policy=policy(primary, secondary),
        throttle=throttle,
    )
    stream = gateway.stream(MESSAGES)
    first = await anext(stream)
    with pytest.raises(LLMUnavailableError, match="connection lost"):
        await anext(stream)
    assert first.delta == "Partial answer"
    assert secondary.calls == []
    assert len(throttle.calls) == 1


async def test_stream_can_fallback_before_first_output_and_reports_actual_identity() -> None:
    primary, secondary = Primary([LLMUnavailableError("down")]), FakeLLM(["Supported [S1]"])
    selected: list[tuple[str, str]] = []
    gateway = LLMGateway(
        primary=target(primary),
        fallbacks=[target(secondary)],
        policy=policy(primary, secondary),
        throttle=ThrottleRecorder(),
        retry=RetryPolicy(attempts_per_provider=1),
        on_selected=lambda p, m: selected.append((p, m)),
    )
    chunks = [c async for c in gateway.stream(MESSAGES)]
    assert "".join(c.delta for c in chunks) == "Supported [S1]"
    assert chunks[-1].usage is not None
    assert selected == [("fake", "scripted-v1")]


class Slow(Primary):
    async def generate(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> LLMResult:
        await asyncio.sleep(10)
        return await super().generate(messages, params)


async def test_total_deadline_and_cancellation_do_not_start_new_attempts() -> None:
    primary, secondary = Slow(["too late"]), FakeLLM(["MUST NOT CALL"])
    throttle = ThrottleRecorder()
    gateway = LLMGateway(
        primary=target(primary),
        fallbacks=[target(secondary)],
        policy=policy(primary, secondary),
        throttle=throttle,
    )
    with pytest.raises(LLMUnavailableError, match="deadline"):
        await gateway.generate(MESSAGES, GenerationParams(timeout_seconds=0.01))
    assert len(throttle.calls) == 1
    assert secondary.calls == []
    task = asyncio.create_task(gateway.generate(MESSAGES))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert secondary.calls == []


class CloseProbe(Primary):
    closed = False

    async def stream(
        self,
        messages: Sequence[ChatMessage],
        params: GenerationParams | None = None,
    ) -> AsyncIterator[LLMChunk]:
        try:
            yield LLMChunk(delta="first")
            await asyncio.sleep(10)
        finally:
            self.closed = True


async def test_closing_gateway_stream_closes_provider_immediately() -> None:
    primary = CloseProbe([])
    gateway = LLMGateway(
        primary=target(primary), policy=policy(primary), throttle=ThrottleRecorder()
    )
    stream = gateway.stream(MESSAGES)
    assert (await anext(stream)).delta == "first"
    await stream.aclose()
    assert primary.closed


async def test_caller_mutation_cannot_change_the_reserved_prompt_during_throttle_wait() -> None:
    entered, proceed = asyncio.Event(), asyncio.Event()

    class WaitingThrottle(ThrottleRecorder):
        async def reserve(self, quota_group: str, tokens: int, limits: ProviderLimits) -> None:
            await super().reserve(quota_group, tokens, limits)
            entered.set()
            await proceed.wait()

    primary = Primary(["Supported [S1]"])
    gateway = LLMGateway(
        primary=target(primary), policy=policy(primary), throttle=WaitingThrottle()
    )
    messages = list(MESSAGES)
    task = asyncio.create_task(gateway.generate(messages))
    await entered.wait()
    messages.clear()
    proceed.set()
    await task
    assert primary.calls[0][0] == tuple(MESSAGES)
