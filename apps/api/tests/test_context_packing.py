import asyncio
import hashlib
import json
import uuid
from collections.abc import Sequence

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.providers.rerankers.base import RerankerProvider, RerankerUnavailableError
from app.providers.rerankers.fake import FakeReranker
from app.rag.context.packer import PackingConfig, pack_context, render_context
from app.rag.context.rerank import rerank_hits
from app.rag.types import Candidate, RankedHit

pytestmark = pytest.mark.unit
DOC, VERSION, KB = uuid.UUID(int=1), uuid.UUID(int=2), uuid.UUID(int=3)


def candidate(text: str, ordinal: int = 0, doc: uuid.UUID = DOC) -> Candidate:
    return Candidate(
        chunk_id=uuid.uuid5(doc, f"{ordinal}:{text}"),
        document_id=doc,
        document_version_id=VERSION,
        knowledge_base_id=KB,
        ordinal=ordinal,
        title="Employee policy",
        content=text,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        token_count=1,
    )


def hits(*sources: Candidate) -> list[RankedHit]:
    return [
        RankedHit(candidate=source, fused_score=1 / (index + 1))
        for index, source in enumerate(sources)
    ]


async def test_budget_uses_rendered_context_not_untrusted_stored_counts() -> None:
    small = candidate("small policy")
    huge = candidate("Oversized text " * 500, 1)
    result = await pack_context(
        hits(huge, small), count_tokens=len, config=PackingConfig(max_tokens=1000)
    )
    assert [item.content for item in result.items] == [small.content]
    assert result.token_count == len(render_context(result.items)) <= 1000
    assert result.items[0].token_count == len(small.content)
    assert result.aliases[0].alias == "S1"  # no gaps from skipped candidates
    assert result.aliases[0].content_hash == small.content_hash
    assert result.aliases[0].document_version_id == VERSION


async def test_model_view_omits_internal_ids_hashes_and_source_urls() -> None:
    source = candidate("Employees receive sixteen weeks.").model_copy(
        update={"source_url": "https://internal.example/private/object"}
    )
    result = await pack_context(hits(source), count_tokens=len)
    rendered = render_context(result.items)
    view = json.loads(rendered)[0]
    assert source.source_url is not None
    assert set(view) == {"alias", "title", "section_path", "location", "content"}
    assert view["alias"] == "S1"
    assert view["content"] == source.content
    for private in (
        str(source.chunk_id),
        str(source.document_id),
        str(VERSION),
        source.content_hash,
        source.source_url,
    ):
        assert private not in rendered
    assert result.aliases[0].chunk_id == source.chunk_id
    assert result.aliases[0].content_hash == source.content_hash
    assert result.aliases[0].source_url == source.source_url
    assert result.token_count == len(rendered)


async def test_caps_hash_and_shingle_redundancy_preserve_stable_aliases() -> None:
    source = candidate("one two three four five six seven eight nine ten")
    duplicate = source.model_copy(update={"chunk_id": uuid.UUID(int=999)})
    near = candidate(source.content.upper(), 1)
    second = candidate("different salary policy content", 2)
    capped = candidate("another chunk from capped document", 3)
    other = candidate("independent handbook", doc=uuid.UUID(int=4))
    inputs = hits(source, duplicate, near, second, capped, other)
    original = [hit.model_copy(deep=True) for hit in inputs]
    config = PackingConfig(max_tokens=5000, max_items=3, per_document_cap=2)
    result = await pack_context(inputs, count_tokens=len, config=config)
    assert [item.content for item in result.items] == [
        source.content,
        second.content,
        other.content,
    ]
    assert [alias.alias for alias in result.aliases] == ["S1", "S2", "S3"]
    assert result == await pack_context(inputs, count_tokens=len, config=config)
    assert inputs == original


async def test_neighbors_keep_independent_source_metadata_and_count_toward_caps() -> None:
    seed, left, right = (
        candidate("body fragment", 2),
        candidate("preceding clause", 1),
        candidate("following clause", 3),
    )
    calls = []

    async def lookup(source: Candidate) -> Sequence[Candidate]:
        calls.append(source.chunk_id)
        return [right, left]

    result = await pack_context(
        hits(seed),
        count_tokens=len,
        neighbors=lookup,
        config=PackingConfig(max_tokens=5000, per_document_cap=2),
    )
    assert calls == [seed.chunk_id]
    assert [item.source.chunk_id for item in result.items] == [seed.chunk_id, left.chunk_id]
    assert result.items[1].source.content_hash == left.content_hash
    assert result.items[0].content == seed.content
    assert not result.items[0].expanded_from  # never merge neighbor text under a seed hash


@pytest.mark.parametrize(
    "field", ["document_id", "document_version_id", "knowledge_base_id", "ordinal"]
)
async def test_out_of_scope_neighbor_callback_fails_closed(field: str) -> None:
    seed = candidate("fragment", 1)
    neighbor = candidate("adjacent", 2).model_copy(
        update={field: 10 if field == "ordinal" else uuid.UUID(int=100)}
    )

    async def lookup(source: Candidate) -> Sequence[Candidate]:
        return [neighbor]

    with pytest.raises(ValueError, match="out-of-scope"):
        await pack_context(hits(seed), count_tokens=len, neighbors=lookup)


async def test_revoked_neighbor_access_is_not_bypassed_or_degraded() -> None:
    async def denied(source: Candidate) -> Sequence[Candidate]:
        raise PermissionError("access revoked")

    with pytest.raises(PermissionError, match="access revoked"):
        await pack_context(hits(candidate("fragment")), count_tokens=len, neighbors=denied)

    async def filtered(source: Candidate) -> Sequence[Candidate]:
        return []

    result = await pack_context(hits(candidate("fragment")), count_tokens=len, neighbors=filtered)
    assert len(result.items) == 1


async def test_tampered_hash_invalid_counter_and_oversized_callback_fail() -> None:
    with pytest.raises(ValueError, match="source hash"):
        await pack_context(
            hits(candidate("original").model_copy(update={"content": "tampered"})), count_tokens=len
        )
    with pytest.raises(ValueError, match="counter"):
        await pack_context([], count_tokens=lambda _: -1)

    async def excessive(source: Candidate) -> Sequence[Candidate]:
        return [candidate("a", 0), candidate("b", 2), candidate("c", 3)]

    with pytest.raises(ValueError, match="more than two"):
        await pack_context(hits(candidate("seed", 1)), count_tokens=len, neighbors=excessive)


@given(
    st.lists(st.text(min_size=1, max_size=100), max_size=12),
    st.integers(min_value=2, max_value=5000),
)
@settings(max_examples=40)
def test_packing_budget_and_alias_invariants(texts: list[str], budget: int) -> None:
    async def check() -> None:
        result = await pack_context(
            hits(*(candidate(text, index) for index, text in enumerate(texts))),
            count_tokens=len,
            config=PackingConfig(max_tokens=budget),
        )
        assert result.token_count <= budget
        assert len(result.items) <= 3  # one document: cap applies
        assert len({source.chunk_id for source in result.aliases}) == len(result.items)
        assert [source.alias for source in result.aliases] == [
            f"S{i + 1}" for i in range(len(result.items))
        ]

    asyncio.run(check())


async def test_fake_reranker_contract_stable_order_and_no_mutation() -> None:
    provider = FakeReranker()
    assert isinstance(provider, RerankerProvider)
    original = hits(
        candidate("unrelated"), candidate("parental leave"), candidate("parental leave policy")
    )
    result = await rerank_hits("parental leave", original, provider)
    assert [hit.candidate.content for hit in result.hits] == [
        "parental leave",
        "parental leave policy",
        "unrelated",
    ]
    assert [hit.rerank_score for hit in original] == [None, None, None]
    assert not result.degraded.any
    assert await provider.rerank("", ["policy"]) == [0]


class SlowReranker(FakeReranker):
    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        await asyncio.sleep(1)
        return await super().rerank(query, passages)


async def test_timeout_degrades_only_when_explicitly_allowed() -> None:
    original = hits(candidate("policy"))
    result = await rerank_hits(
        "policy", original, SlowReranker(), timeout_seconds=0.01, allow_degraded=True
    )
    assert result.degraded.rerank_bypassed
    assert result.hits == tuple(original)
    with pytest.raises(RerankerUnavailableError):
        await rerank_hits("policy", original, SlowReranker(), timeout_seconds=0.01)


class DeniedReranker(FakeReranker):
    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        raise PermissionError("policy denies external provider")


async def test_policy_error_and_cancellation_never_degrade() -> None:
    with pytest.raises(PermissionError):
        await rerank_hits(
            "policy", hits(candidate("policy")), DeniedReranker(), allow_degraded=True
        )
    task = asyncio.create_task(
        rerank_hits("policy", hits(candidate("policy")), SlowReranker(), allow_degraded=True)
    )
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
