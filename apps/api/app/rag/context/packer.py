"""DB-free evidence packing. Caller supplies the generation tokenizer and authorized neighbors.

Neighbors must be fetched with the SAME active-generation and authorization predicate as search.
Candidate intentionally has no generation ID: the callback must bind that scope itself. Each
neighbor retains its own alias/hash/location; text from different chunks is never merged under
one misleading source alias. Generation must use render_context, reserving other prompt tokens
before passing max_tokens here.
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from app.rag.types import Candidate, EvidenceItem, RankedHit, SourceAlias

TokenCounter = Callable[[str], int]
NeighborLookup = Callable[[Candidate], Awaitable[Sequence[Candidate]]]
_WORDS = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class PackingConfig:
    max_tokens: int = 4500
    max_items: int = 8
    per_document_cap: int = 3
    redundancy_threshold: float = 0.85
    max_candidates: int = 200
    max_content_characters: int = 50_000

    def __post_init__(self) -> None:
        if (
            min(
                self.max_tokens,
                self.max_items,
                self.per_document_cap,
                self.max_candidates,
                self.max_content_characters,
            )
            < 1
        ):
            raise ValueError("packing limits must be positive")
        if not 0 < self.redundancy_threshold <= 1:
            raise ValueError("redundancy threshold must be in (0, 1]")


@dataclass(frozen=True)
class PackedContext:
    items: tuple[EvidenceItem, ...]
    token_count: int

    @property
    def aliases(self) -> tuple[SourceAlias, ...]:
        return tuple(item.source for item in self.items)


DEFAULT_CONFIG = PackingConfig()


def render_context(items: Sequence[EvidenceItem]) -> str:
    """Stable JSON data, NOT prompt instructions. The generation prompt must delimit it."""
    return json.dumps(
        [
            {"source": item.source.model_dump(mode="json"), "content": item.content}
            for item in items
        ],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _shingles(text: str) -> frozenset[tuple[str, ...]]:
    words = _WORDS.findall(text.casefold())
    if len(words) < 5:
        return frozenset({tuple(words)}) if words else frozenset()
    return frozenset(tuple(words[i : i + 5]) for i in range(len(words) - 4))


def _similar(left: frozenset[tuple[str, ...]], right: frozenset[tuple[str, ...]]) -> float:
    union = left | right
    return len(left & right) / len(union) if union else 0


def _item(candidate: Candidate, number: int, score: float | None) -> EvidenceItem:
    source = SourceAlias(
        alias=f"S{number}",
        chunk_id=candidate.chunk_id,
        document_id=candidate.document_id,
        document_version_id=candidate.document_version_id,
        title=candidate.title,
        version_number=candidate.version_number,
        section_path=candidate.section_path,
        location=candidate.location.model_copy(deep=True),
        source_url=candidate.source_url,
        content_hash=candidate.content_hash,
    )
    return EvidenceItem(source=source, content=candidate.content, token_count=0, rerank_score=score)


async def pack_context(
    hits: Sequence[RankedHit],
    *,
    count_tokens: TokenCounter,
    config: PackingConfig = DEFAULT_CONFIG,
    neighbors: NeighborLookup | None = None,
) -> PackedContext:
    """Pack in supplied relevance order, whole chunks only. Oversized chunks are skipped, not
    truncated (citation hashes remain accurate). Callback exceptions propagate, never degrade.
    Expansion is opt-in: supply a callback returning zero to two adjacent authorized fragments.
    """
    if len(hits) > config.max_candidates:
        raise ValueError("too many packing candidates")
    selected: list[EvidenceItem] = []
    counts: Counter[object] = Counter()
    hashes: set[str] = set()
    ids: set[object] = set()
    signatures: list[frozenset[tuple[str, ...]]] = []

    def count(text: str) -> int:
        value = count_tokens(text)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("token counter must return a nonnegative integer")
        return value

    def add(candidate: Candidate, score: float | None) -> bool:
        if len(candidate.content) > config.max_content_characters:
            return False
        if hashlib.sha256(candidate.content.encode()).hexdigest() != candidate.content_hash:
            raise ValueError("candidate content does not match its source hash")
        if (
            candidate.chunk_id in ids
            or candidate.content_hash in hashes
            or len(selected) >= config.max_items
            or counts[candidate.document_id] >= config.per_document_cap
        ):
            return False
        signature = _shingles(candidate.content)
        if any(_similar(signature, old) >= config.redundancy_threshold for old in signatures):
            return False
        item = _item(candidate, len(selected) + 1, score)
        item.token_count = count(item.content)
        if count(render_context([*selected, item])) > config.max_tokens:
            return False
        selected.append(item)
        ids.add(candidate.chunk_id)
        hashes.add(candidate.content_hash)
        signatures.append(signature)
        counts[candidate.document_id] += 1
        return True

    for hit in hits:
        if len(selected) >= config.max_items:
            break
        if not add(hit.candidate, hit.rerank_score) or neighbors is None:
            continue
        adjacent = await neighbors(hit.candidate)
        if len(adjacent) > 2:
            raise ValueError("neighbor lookup returned more than two fragments")
        for candidate in sorted(
            adjacent, key=lambda candidate: (candidate.ordinal, candidate.chunk_id)
        ):
            seed = hit.candidate
            if (
                candidate.document_id,
                candidate.document_version_id,
                candidate.knowledge_base_id,
            ) != (seed.document_id, seed.document_version_id, seed.knowledge_base_id) or abs(
                candidate.ordinal - seed.ordinal
            ) != 1:
                raise ValueError("neighbor lookup returned an out-of-scope fragment")
            add(candidate, None)
    items = tuple(selected)
    tokens = count(render_context(items))
    # Even an empty serialized context needs a small prompt allowance.
    if tokens > config.max_tokens:
        raise ValueError("token budget cannot fit the empty context envelope")
    return PackedContext(items, tokens)
