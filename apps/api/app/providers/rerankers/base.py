"""Contract: rerankers (plan §19, T1.0). Implementations: Codex T5.1.

Scores are only comparable within one model (never across models). On timeout or failure raise
`RerankerUnavailableError`; the orchestrator decides whether degraded (fused-order) mode is allowed.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


class RerankerUnavailableError(RuntimeError):
    """Model unavailable or timed out."""


@runtime_checkable
class RerankerProvider(Protocol):
    @property
    def model_id(self) -> str: ...

    @property
    def is_external(self) -> bool: ...

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        """One relevance score per passage, same order as `passages` (higher = more relevant)."""
        ...
