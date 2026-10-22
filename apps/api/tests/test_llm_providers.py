import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
import pytest
import respx

from app.providers.llm.base import (
    ChatMessage,
    GenerationParams,
    LLMProvider,
    LLMRateLimitedError,
    LLMUnavailableError,
    Role,
)
from app.providers.llm.fake import FakeLLM
from app.providers.llm.openai_compatible import LLMRequestError, OpenAICompatibleLLM, retry_after

pytestmark = pytest.mark.unit
URL = "https://llm.test/v1/chat/completions"
MESSAGES = [
    ChatMessage(role=Role.SYSTEM, content="Grounded only."),
    ChatMessage(role=Role.USER, content="Leave?"),
]


def provider(
    *,
    api_key: str | None = None,
    max_event_bytes: int = 64 * 1024,
    max_response_bytes: int = 2 * 1024**2,
) -> OpenAICompatibleLLM:
    return OpenAICompatibleLLM(
        base_url="https://llm.test/v1",
        provider_id="configured",
        model_id="pinned-model",
        is_external=True,
        api_key=api_key,
        max_event_bytes=max_event_bytes,
        max_response_bytes=max_response_bytes,
    )


def payload(text: str = "Twelve weeks. [S1]", *, streaming: bool = False) -> dict[str, object]:
    content = {"role": "assistant", "content": text}
    return {
        "model": "pinned-model",
        "choices": [
            {"index": 0, "delta" if streaming else "message": content, "finish_reason": "stop"}
        ],
        "usage": {"prompt_tokens": 40, "completion_tokens": 8},
    }


async def test_fake_script_errors_exhaustion_and_contract() -> None:
    fake = FakeLLM(["Valid [S1]", LLMRateLimitedError("limited"), "No citation"])
    assert isinstance(fake, LLMProvider)
    first = await fake.generate(MESSAGES)
    assert first.text == "Valid [S1]"
    assert first.usage.estimated
    with pytest.raises(LLMRateLimitedError):
        await fake.generate(MESSAGES)
    chunks = [c async for c in fake.stream(MESSAGES)]
    assert chunks[0].delta == "No citation"
    assert chunks[-1].finish_reason == "stop"
    assert chunks[-1].usage is not None
    with pytest.raises(RuntimeError, match="exhausted"):
        await fake.generate(MESSAGES)
    assert len(fake.calls) == 4


@respx.mock
async def test_configured_request_identity_usage_and_no_tools() -> None:
    route = respx.post(URL).respond(200, json=payload())
    llm = provider(api_key="private-test-value")
    try:
        assert isinstance(llm, LLMProvider)
        result = await llm.generate(MESSAGES, GenerationParams(stop=("END",)))
        body = json.loads(route.calls[0].request.content)
        assert body == {
            "model": "pinned-model",
            "messages": [m.model_dump(mode="json") for m in MESSAGES],
            "max_tokens": 1024,
            "temperature": 0.1,
            "stream": False,
            "stop": ["END"],
        }
        assert route.calls[0].request.headers["authorization"] == "Bearer private-test-value"
        assert result.model == "pinned-model"
        assert result.provider == "configured"
        assert result.usage.input_tokens == 40
        assert result.usage.output_tokens == 8
        assert not result.usage.estimated
    finally:
        await llm.aclose()


@pytest.mark.parametrize(
    ("status", "exception"),
    [
        (401, PermissionError),
        (403, PermissionError),
        (400, LLMRequestError),
        (404, LLMRequestError),
        (429, LLMRateLimitedError),
        (503, LLMUnavailableError),
        (302, LLMUnavailableError),
    ],
)
@respx.mock
async def test_status_is_classified_without_private_body_or_automatic_retry(
    status: int,
    exception: type[Exception],
) -> None:
    route = respx.post(URL).respond(
        status, text="SECRET BODY", headers={"retry-after": "12", "location": "https://other.test"}
    )
    llm = provider()
    try:
        with pytest.raises(exception) as exc:
            await llm.generate(MESSAGES)
        assert "SECRET BODY" not in str(exc.value)
        assert route.call_count == 1
        if isinstance(exc.value, LLMRateLimitedError):
            assert exc.value.retry_after_seconds == 12
    finally:
        await llm.aclose()


def test_retry_after_seconds_and_dates_are_minimum_waits_not_capped() -> None:
    assert retry_after("90000") == 90000
    now = datetime(2026, 10, 22, tzinfo=UTC)
    assert retry_after("Thu, 22 Oct 2026 00:01:00 GMT", now=now) == 60
    assert retry_after("Wed, 21 Oct 2026 00:01:00 GMT", now=now) == 0
    assert retry_after("NaN") is None
    assert retry_after("inf") is None
    assert retry_after("bad") is None
    assert retry_after(None) is None


@respx.mock
async def test_missing_usage_is_explicitly_estimated() -> None:
    body = payload("é")
    body.pop("usage")
    respx.post(URL).respond(200, json=body)
    llm = provider()
    try:
        result = await llm.generate(MESSAGES)
        assert result.usage.estimated
        assert result.usage.output_tokens == 2
    finally:
        await llm.aclose()


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"model": "substituted", "choices": []},
        {"model": "pinned-model", "choices": [{"index": 0, "finish_reason": "tool_calls"}]},
        {
            "model": "pinned-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": "ok",
                        "tool_calls": [{"id": "evil"}],
                    },
                }
            ],
        },
        {**payload(), "usage": {"prompt_tokens": True, "completion_tokens": 1}},
        {**payload(), "usage": {"prompt_tokens": -1, "completion_tokens": 1}},
    ],
)
@respx.mock
async def test_malformed_or_substituted_response_fails_closed(body: dict[str, object]) -> None:
    respx.post(URL).respond(200, json=body)
    llm = provider()
    try:
        with pytest.raises(LLMUnavailableError):
            await llm.generate(MESSAGES)
    finally:
        await llm.aclose()


class Parts(httpx.AsyncByteStream):
    def __init__(self, parts: list[bytes], delay: float = 0) -> None:
        self.parts, self.delay = parts, delay

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for part in self.parts:
            if self.delay:
                await asyncio.sleep(self.delay)
            yield part


def event(body: dict[str, object]) -> bytes:
    return b"data: " + json.dumps(body).encode() + b"\r\n\r\n"


@respx.mock
async def test_stream_fragmentation_finish_then_usage_only_and_done() -> None:
    data = payload("Twelve weeks. [S1]", streaming=True)
    data["usage"] = None
    raw = (
        b": heartbeat\r\n\r\n"
        + event(data)
        + event(
            {
                "model": "pinned-model",
                "choices": [],
                "usage": {"prompt_tokens": 40, "completion_tokens": 8},
            }
        )
        + b"data: [DONE]\r\n\r\n"
    )
    # Every byte, including CR/LF and UTF-8 sequences, may arrive in a different HTTP chunk.
    route = respx.post(URL).respond(
        200,
        headers={"content-type": "text/event-stream"},
        stream=Parts([bytes([b]) for b in raw]),
    )
    llm = provider()
    try:
        chunks = [c async for c in llm.stream(MESSAGES)]
        assert "".join(c.delta for c in chunks) == "Twelve weeks. [S1]"
        assert len(chunks) == 2
        assert chunks[-1].finish_reason == "stop"
        assert chunks[-1].usage is not None
        assert chunks[-1].usage.output_tokens == 8
        assert not chunks[-1].usage.estimated
        assert json.loads(route.calls[0].request.content)["stream_options"] == {
            "include_usage": True
        }
    finally:
        await llm.aclose()


@pytest.mark.parametrize(
    ("raw", "limit", "reason"),
    [
        (event(payload("ok", streaming=True)), 4096, "without DONE"),
        (b"data: [DONE]\n\n", 4096, "did not finish"),
        (b"data: {bad json}\n\n", 4096, "JSON"),
        (b"data: " + b"x" * 100, 80, "exceeds"),
        (event({"model": "other", "choices": []}), 4096, "unexpected model"),
        (b"data: {", 4096, "Truncated"),
        (
            event(
                {
                    "model": "pinned-model",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": []}],
                }
            ),
            4096,
            "text answer",
        ),
    ],
)
@respx.mock
async def test_stream_malformed_truncated_or_oversized_fails(
    raw: bytes,
    limit: int,
    reason: str,
) -> None:
    respx.post(URL).respond(200, headers={"content-type": "text/event-stream"}, content=raw)
    llm = provider(max_event_bytes=limit)
    try:
        with pytest.raises(LLMUnavailableError, match=reason):
            _ = [c async for c in llm.stream(MESSAGES)]
    finally:
        await llm.aclose()


@respx.mock
async def test_byte_budget_and_total_deadline() -> None:
    route = respx.post(URL).respond(200, content=b"x" * 101)
    llm = provider(max_response_bytes=100)
    try:
        with pytest.raises(LLMUnavailableError, match="limit"):
            await llm.generate(MESSAGES)
        route.respond(200, stream=Parts([b"{", b"}"], delay=0.1))
        with pytest.raises(LLMUnavailableError, match="timed out"):
            await llm.generate(MESSAGES, GenerationParams(timeout_seconds=0.01))
    finally:
        await llm.aclose()


@pytest.mark.parametrize(
    "params",
    [
        GenerationParams(max_output_tokens=0),
        GenerationParams(temperature=float("nan")),
        GenerationParams(timeout_seconds=float("inf")),
        GenerationParams(stop=("",)),
    ],
)
async def test_invalid_params_rejected_before_script_or_network(params: GenerationParams) -> None:
    fake = FakeLLM(["unused"])
    with pytest.raises(ValueError, match="parameters"):
        await fake.generate(MESSAGES, params)
    assert fake.calls == []


@pytest.mark.parametrize(
    "url",
    [
        "https://user:secret@llm.test/v1",
        "https://llm.test/v1?api_key=secret",
        "https://llm.test/v1#fragment",
        "http://llm.test/v1",
    ],
)
def test_external_endpoint_requires_tls_and_no_embedded_credentials(url: str) -> None:
    with pytest.raises(ValueError, match="endpoint"):
        OpenAICompatibleLLM(base_url=url, provider_id="x", model_id="y", is_external=True)
