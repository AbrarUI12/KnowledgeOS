"""Explicit profile-controlled rerank degradation; authorization failures never degrade."""

import asyncio
import math
from collections.abc import Sequence
from dataclasses import dataclass

from app.providers.rerankers.base import RerankerProvider, RerankerUnavailableError
from app.rag.types import DegradedFlags, RankedHit


@dataclass(frozen=True)
class RerankedContext:
    hits: tuple[RankedHit, ...]
    degraded: DegradedFlags
    model_id: str


async def rerank_hits(
    query: str,
    hits: Sequence[RankedHit],
    provider: RerankerProvider,
    *,
    timeout_seconds: float = 5,
    allow_degraded: bool = False,
) -> RerankedContext:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("rerank timeout must be finite and positive")
    try:
        async with asyncio.timeout(timeout_seconds):
            scores = await provider.rerank(query, [hit.candidate.content for hit in hits])
        if len(scores) != len(hits) or any(
            isinstance(score, bool)
            or not isinstance(score, (float, int))
            or not math.isfinite(score)
            for score in scores
        ):
            raise RerankerUnavailableError("Reranker returned invalid scores.")
    except (TimeoutError, RerankerUnavailableError):
        if not allow_degraded:
            raise RerankerUnavailableError("Reranking is unavailable.") from None
        return RerankedContext(
            tuple(hit.model_copy(update={"rerank_score": None}) for hit in hits),
            DegradedFlags(rerank_bypassed=True),
            provider.model_id,
        )
    scored = [
        hit.model_copy(update={"rerank_score": float(score)})
        for hit, score in zip(hits, scores, strict=True)
    ]
    # Stable sort retains fused order for equal scores.
    ordered = tuple(sorted(scored, key=lambda hit: -(hit.rerank_score or 0.0)))
    return RerankedContext(ordered, DegradedFlags(), provider.model_id)
