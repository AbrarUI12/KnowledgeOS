"""One bounded attempt at a configured OpenAI-compatible chat endpoint.

No tool calling, redirects, retries, model substitution or logging of prompts/credentials.
Gateway policy owns retries/fallback. Streaming is bounded before line/event decoding.
Schema: https://developers.openai.com/api/reference/resources/chat/subresources/completions
"""

import asyncio
import json
import math
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.providers.llm.base import (
    ChatMessage,
    GenerationParams,
    LLMChunk,
    LLMRateLimitedError,
    LLMResult,
    LLMUnavailableError,
)
from app.providers.llm.validation import estimated_usage, validate_request
from app.rag.types import Usage


class LLMRequestError(RuntimeError):
    """Permanent configuration/request failure: never automatically retry or fall back."""


def retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                return None
            seconds = (date - (now or datetime.now(UTC))).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def _usage(raw: object) -> Usage | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise LLMUnavailableError("Invalid generation usage.")
    values = [raw.get("prompt_tokens"), raw.get("completion_tokens")]
    if any(type(v) is not int or not 0 <= v <= 10**9 for v in values):
        raise LLMUnavailableError("Invalid generation usage.")
    return Usage(input_tokens=values[0], output_tokens=values[1], estimated=False)


def _object(raw: bytes) -> dict[str, Any]:
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise LLMUnavailableError("Invalid generation JSON.") from None
    if not isinstance(result, dict) or "error" in result:
        raise LLMUnavailableError("Invalid generation response.")
    return result


def _status(response: httpx.Response) -> None:
    status = response.status_code
    if status == 429:
        raise LLMRateLimitedError(
            "Generation endpoint rate limited.",
            retry_after_seconds=retry_after(response.headers.get("Retry-After")),
        )
    if status in {401, 403}:
        raise PermissionError("Generation endpoint denied access.")
    if 400 <= status < 500 and status not in {408, 425}:
        raise LLMRequestError("Generation endpoint rejected its configuration or request.")
    if not 200 <= status < 300:
        raise LLMUnavailableError("Generation endpoint unavailable.")


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        base_url: str,
        provider_id: str,
        model_id: str,
        is_external: bool,
        api_key: str | None = None,
        max_response_bytes: int = 2 * 1024**2,
        max_event_bytes: int = 64 * 1024,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or (is_external and parsed.scheme != "https")
        ):
            raise ValueError("invalid generation endpoint")
        if not provider_id or not model_id or min(max_response_bytes, max_event_bytes) < 1:
            raise ValueError("generation identity and positive response limits are required")
        self._provider_id, self._model_id, self._external = provider_id, model_id, is_external
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._max_response, self._max_event = max_response_bytes, max_event_bytes
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(follow_redirects=False)

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def is_external(self) -> bool:
        return self._external

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    def _body(
        self, messages: Sequence[ChatMessage], params: GenerationParams, *, stream: bool
    ) -> dict[str, object]:
        validate_request(messages, params)
        body: dict[str, object] = {
            "model": self.model_id,
            "messages": [message.model_dump(mode="json") for message in messages],
            "max_tokens": params.max_output_tokens,
            "temperature": params.temperature,
            "stream": stream,
        }
        if params.stop:
            body["stop"] = list(params.stop)
        if stream:
            body["stream_options"] = {"include_usage": True}
        return body

    def _choice(self, payload: dict[str, Any], *, usage_only: bool = False) -> dict[str, Any]:
        if payload.get("model") != self.model_id:
            raise LLMUnavailableError("Generation endpoint returned an unexpected model.")
        choices = payload.get("choices")
        if usage_only and choices == [] and payload.get("usage") is not None:
            return {}
        if (
            not isinstance(choices, list)
            or len(choices) != 1
            or not isinstance(choices[0], dict)
            or type(choices[0].get("index")) is not int
            or choices[0]["index"] != 0
        ):
            raise LLMUnavailableError("Invalid generation choice.")
        choice: dict[str, Any] = choices[0]
        if choice.get("finish_reason") not in (None, "stop", "length"):
            raise LLMUnavailableError("Generation did not finish with a text answer.")
        return choice

    async def generate(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> LLMResult:
        params = params or GenerationParams()
        body = self._body(messages, params, stream=False)
        try:
            async with (
                asyncio.timeout(params.timeout_seconds),
                self._client.stream(
                    "POST",
                    self._url,
                    headers=self._headers,
                    json=body,
                    timeout=httpx.Timeout(
                        params.timeout_seconds, connect=min(10, params.timeout_seconds)
                    ),
                    follow_redirects=False,
                ) as response,
            ):
                _status(response)
                content = bytearray()
                async for part in response.aiter_bytes():
                    if len(content) + len(part) > self._max_response:
                        raise LLMUnavailableError("Generation response exceeds its limit.")
                    content.extend(part)
            payload = _object(bytes(content))
            choice = self._choice(payload)
            message = choice.get("message")
            if (
                not isinstance(message, dict)
                or message.get("role") != "assistant"
                or not isinstance(message.get("content"), str)
                or message.get("tool_calls")
                or message.get("function_call")
                or choice.get("finish_reason") is None
            ):
                raise LLMUnavailableError("Invalid generation message.")
            text = message["content"]
            return LLMResult(
                text=text,
                model=self.model_id,
                provider=self.provider_id,
                finish_reason=choice["finish_reason"],
                usage=_usage(payload.get("usage")) or estimated_usage(messages, text),
            )
        except (httpx.HTTPError, TimeoutError):
            raise LLMUnavailableError("Generation endpoint unavailable or timed out.") from None

    async def _events(self, response: httpx.Response) -> AsyncIterator[bytes]:
        buffer, data = bytearray(), bytearray()
        total = 0
        async for part in response.aiter_bytes():
            total += len(part)
            if total > self._max_response:
                raise LLMUnavailableError("Generation stream exceeds its limit.")
            # Split each network part before extending, so a newline-free line is bounded too.
            for piece in part.splitlines(keepends=True):
                buffer.extend(piece)
                if len(buffer) + len(data) > self._max_event:
                    raise LLMUnavailableError("Generation event exceeds its limit.")
                if not buffer.endswith(b"\n"):
                    continue
                line = bytes(buffer).rstrip(b"\r\n")
                buffer.clear()
                if not line:
                    if data:
                        yield bytes(data).rstrip(b"\n")
                        data.clear()
                elif line.startswith(b"data:"):
                    data.extend(line[5:].removeprefix(b" ") + b"\n")
        if buffer or data:
            raise LLMUnavailableError("Truncated generation event.")

    async def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> AsyncIterator[LLMChunk]:
        params = params or GenerationParams()
        body = self._body(messages, params, stream=True)
        usage, finish = None, None
        text: list[str] = []
        try:
            async with (
                asyncio.timeout(params.timeout_seconds),
                self._client.stream(
                    "POST",
                    self._url,
                    headers=self._headers,
                    json=body,
                    timeout=httpx.Timeout(
                        params.timeout_seconds, connect=min(10, params.timeout_seconds)
                    ),
                    follow_redirects=False,
                ) as response,
            ):
                _status(response)
                if response.headers.get("content-type", "").split(";")[0] != "text/event-stream":
                    raise LLMUnavailableError("Invalid generation stream type.")
                async for event in self._events(response):
                    if event == b"[DONE]":
                        if finish is None:
                            raise LLMUnavailableError("Generation stream did not finish.")
                        yield LLMChunk(
                            finish_reason=finish,
                            usage=usage or estimated_usage(messages, "".join(text)),
                        )
                        return
                    payload = _object(event)
                    choice = self._choice(payload, usage_only=True)
                    measured = _usage(payload.get("usage"))
                    if measured is not None:
                        usage = measured
                    if not choice:
                        continue
                    delta = choice.get("delta")
                    if (
                        not isinstance(delta, dict)
                        or delta.get("role", "assistant") != "assistant"
                        or delta.get("tool_calls")
                        or delta.get("function_call")
                        or finish is not None
                    ):
                        raise LLMUnavailableError("Invalid generation delta.")
                    content = delta.get("content")
                    if content is not None:
                        if not isinstance(content, str):
                            raise LLMUnavailableError("Invalid generation delta content.")
                        text.append(content)
                        if content:
                            yield LLMChunk(delta=content)
                    finish = choice.get("finish_reason")
                raise LLMUnavailableError("Generation stream ended without DONE.")
        except (httpx.HTTPError, TimeoutError):
            raise LLMUnavailableError("Generation stream unavailable or timed out.") from None
