"""Explicit deterministic test provider, never an automatic model fallback."""

import hashlib
import math
import re
from collections.abc import Sequence

from app.providers.embeddings.validation import texts_list


class FakeEmbeddingProvider:
    provider_id = "fake"
    model_id = "fake-hash-embedding-v2"
    normalized = True
    max_batch = 64
    is_external = False

    def __init__(self, dimension: int = 1024) -> None:
        if dimension < 1:
            raise ValueError("dimension must be positive")
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _vector(self, text: str) -> list[float]:
        result = [0.0] * self.dimension
        words = re.findall(r"\w+", text.casefold()) or [text]
        for word in words:
            bucket = int.from_bytes(hashlib.sha256(word.encode()).digest()[:8]) % self.dimension
            result[bucket] += 1
        norm = math.hypot(*result)
        return [value / norm for value in result]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._vector(text) for text in texts_list(texts)]

    async def embed_query(self, text: str) -> list[float]:
        return self._vector(texts_list([text])[0])
