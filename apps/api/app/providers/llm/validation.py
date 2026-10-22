"""Bounds shared by generation adapters, not changes to the T1.0 contract."""

import math
from collections.abc import Sequence

from app.providers.llm.base import ChatMessage, GenerationParams
from app.rag.types import Usage


def validate_request(messages: Sequence[ChatMessage], params: GenerationParams) -> None:
    if not 1 <= len(messages) <= 64 or sum(len(m.content) for m in messages) > 200_000:
        raise ValueError("generation messages exceed their bounds")
    if (
        not 1 <= params.max_output_tokens <= 32_768
        or not math.isfinite(params.temperature)
        or not 0 <= params.temperature <= 2
        or not math.isfinite(params.timeout_seconds)
        or not 0 < params.timeout_seconds <= 600
        or len(params.stop) > 4
        or any(not stop or len(stop) > 256 for stop in params.stop)
    ):
        raise ValueError("invalid generation parameters")


def estimated_usage(messages: Sequence[ChatMessage], text: str) -> Usage:
    """Conservative UTF-8-byte estimate, never represented as provider-measured tokens.

    The gateway's configured model token counter is used for quota reservations; this fallback
    is only for accounting when the endpoint omits its measured usage.
    """
    return Usage(
        input_tokens=sum(len(m.content.encode("utf-8")) + 8 for m in messages),
        output_tokens=len(text.encode("utf-8")),
        estimated=True,
    )
