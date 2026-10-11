"""Contract: generation models (plan §21, §25, T1.0). Implementations: Codex T5.2.

One OpenAI-compatible adapter covers Ollama, Groq, Gemini and OpenRouter (D-005). No tool calling:
retrieved evidence can never grant tools or permissions.
"""

from collections.abc import AsyncIterator, Sequence
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from app.rag.types import Usage


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ChatMessage(BaseModel):
    model_config = ConfigDict(frozen=True)

    role: Role
    content: str


class GenerationParams(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_output_tokens: int = 1024
    temperature: float = 0.1
    timeout_seconds: float = 60.0
    stop: tuple[str, ...] = ()


class LLMResult(BaseModel):
    text: str
    model: str
    provider: str
    finish_reason: str | None = None
    usage: Usage = Usage()


class LLMChunk(BaseModel):
    """A streamed delta. The final chunk carries `finish_reason` and `usage`."""

    delta: str = ""
    finish_reason: str | None = None
    usage: Usage | None = None


class LLMRateLimitedError(RuntimeError):
    def __init__(self, message: str, *, retry_after_seconds: float | None = None) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class LLMUnavailableError(RuntimeError):
    """Provider error or timeout (the gateway may fall back to an allowed model)."""


@runtime_checkable
class LLMProvider(Protocol):
    @property
    def provider_id(self) -> str: ...  # "ollama", "groq", "gemini", "openrouter", "fake"

    @property
    def model_id(self) -> str: ...

    @property
    def is_external(self) -> bool: ...

    async def generate(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> LLMResult: ...

    def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> AsyncIterator[LLMChunk]: ...
