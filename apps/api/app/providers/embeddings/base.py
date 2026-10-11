"""Contract: embedding providers (ADR-006, plan §13, T1.0). Implementations: Codex T4.1.

Rules: vectors have exactly `dimension` floats (1024 for the first index schema) and are
L2-normalized when `normalized` is True. Never substitute another model when this one fails
(plan §25.2): raise `EmbeddingUnavailableError` and let the job retry.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


class EmbeddingUnavailableError(RuntimeError):
    """The model/endpoint is unavailable (retryable)."""


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def provider_id(self) -> str: ...  # e.g. "sentence-transformers", "openai-compatible:tei"

    @property
    def model_id(self) -> str: ...  # exact model, recorded on the index generation

    @property
    def dimension(self) -> int: ...

    @property
    def normalized(self) -> bool: ...

    @property
    def max_batch(self) -> int: ...

    @property
    def is_external(self) -> bool: ...  # True if text leaves the deployment (model policy)

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...
