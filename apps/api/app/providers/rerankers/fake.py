"""Deterministic contract-compatible lexical fake, never a production fallback."""

import re
from collections.abc import Sequence


class FakeReranker:
    model_id = "fake-overlap-reranker"
    is_external = False

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        words = set(re.findall(r"\w+", query.lower()))
        return [
            len(words & set(re.findall(r"\w+", passage.lower()))) / len(words) if words else 0.0
            for passage in passages
        ]
