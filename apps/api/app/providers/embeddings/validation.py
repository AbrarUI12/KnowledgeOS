"""Shared numerical guards; invalid vectors never reach an index."""

import math
from collections.abc import Sequence

from app.providers.embeddings.base import EmbeddingUnavailableError


class EmbeddingDimensionError(ValueError):
    """Permanent configuration/output mismatch, not a reason to substitute a model."""


def texts_list(texts: Sequence[str]) -> list[str]:
    if isinstance(texts, str) or any(not isinstance(text, str) for text in texts):
        raise ValueError("embedding inputs must be a sequence of strings")
    return list(texts)


def vectors(raw: object, *, count: int, dimension: int, normalized: bool) -> list[list[float]]:
    if not isinstance(raw, list) or len(raw) != count:
        raise EmbeddingUnavailableError("Embedding response has an invalid batch size.")
    result: list[list[float]] = []
    for values in raw:
        if not isinstance(values, list):
            raise EmbeddingUnavailableError("Embedding response has an invalid vector.")
        if len(values) != dimension:
            raise EmbeddingDimensionError(
                f"Expected dimension {dimension}, received {len(values)}."
            )
        if any(isinstance(value, bool) or not isinstance(value, (float, int)) for value in values):
            raise EmbeddingUnavailableError("Embedding response has nonnumeric values.")
        try:
            vector = [float(value) for value in values]
        except OverflowError:
            raise EmbeddingUnavailableError("Embedding response has out-of-range values.") from None
        if not all(math.isfinite(value) for value in vector):
            raise EmbeddingUnavailableError("Embedding response has nonfinite values.")
        norm = math.hypot(*vector)
        if not math.isfinite(norm) or norm == 0:
            raise EmbeddingUnavailableError("Embedding response has an invalid norm.")
        result.append([value / norm for value in vector] if normalized else vector)
    return result
