"""Scripted DB-free LLM for deterministic application tests (not a network fallback)."""

from collections import deque
from collections.abc import AsyncIterator, Sequence

from app.providers.llm.base import ChatMessage, GenerationParams, LLMChunk, LLMResult
from app.providers.llm.validation import estimated_usage, validate_request


class FakeLLM:
    provider_id = "fake"
    model_id = "scripted-v1"
    is_external = False

    def __init__(self, script: Sequence[str | Exception]) -> None:
        self._script = deque(script)
        self.calls: list[tuple[tuple[ChatMessage, ...], GenerationParams]] = []

    async def generate(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> LLMResult:
        params = params or GenerationParams()
        validate_request(messages, params)
        self.calls.append((tuple(m.model_copy(deep=True) for m in messages), params))
        if not self._script:
            raise RuntimeError("FakeLLM script exhausted")
        item = self._script.popleft()
        if isinstance(item, Exception):
            raise item
        return LLMResult(
            text=item,
            model=self.model_id,
            provider=self.provider_id,
            finish_reason="stop",
            usage=estimated_usage(messages, item),
        )

    async def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> AsyncIterator[LLMChunk]:
        result = await self.generate(messages, params)
        if result.text:
            yield LLMChunk(delta=result.text)
        yield LLMChunk(finish_reason=result.finish_reason, usage=result.usage)
