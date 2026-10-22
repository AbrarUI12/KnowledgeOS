"""Inferred-filter relaxation (S24) and query helpers: pure, against the contract fake."""

import uuid

import pytest

from app.ingestion.canonical import SourceLocation
from app.providers.search.base import HybridSearchRequest, QueryFilters, SearchScope
from app.providers.search.postgres import UnsupportedFilter, compile_filters, query_identifiers
from app.rag.retrieval.relaxation import search_relaxing_inferred_filters
from app.rag.types import Candidate
from tests.fakes import FakeSearchBackend, IndexedChunk

pytestmark = pytest.mark.unit
ORG, KB, OTHER_KB = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def chunk(text: str, *, kb: uuid.UUID = KB, principals: frozenset[str] = frozenset({"role:member"}),
          document_type: str = "policy") -> IndexedChunk:  # fmt: skip
    return IndexedChunk(
        candidate=Candidate(
            chunk_id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            document_version_id=uuid.uuid4(),
            knowledge_base_id=kb,
            ordinal=0,
            title="Handbook",
            content=text,
            content_hash="0" * 64,
            token_count=3,
            location=SourceLocation(),
        ),
        organization_id=ORG,
        access_principals=principals,
        document_type=document_type,
    )


BACKEND = FakeSearchBackend(
    [
        chunk("parental leave is sixteen weeks"),
        chunk("parental leave for executives", principals=frozenset({"group:exec"})),
        chunk("parental leave elsewhere", kb=OTHER_KB),
    ]
)


def request(**filters: object) -> HybridSearchRequest:
    return HybridSearchRequest(
        scope=SearchScope(
            organization_id=ORG, knowledge_base_ids=(KB,), principal_tokens=("role:member",)
        ),
        query="parental leave",
        filters=QueryFilters.model_validate(filters),
    )


async def test_an_inferred_filter_that_empties_the_result_is_relaxed_once() -> None:
    result, relaxed = await search_relaxing_inferred_filters(
        BACKEND, request(document_types=("contract",)), inferred={"document_types"}
    )

    assert relaxed == ("document_types",)
    assert [h.candidate.content for h in result.lexical] == ["parental leave is sixteen weeks"]


async def test_explicit_filters_and_authorization_are_never_relaxed() -> None:
    explicit, relaxed = await search_relaxing_inferred_filters(
        BACKEND, request(document_types=("contract",)), inferred=()
    )
    assert relaxed == ()
    assert explicit.lexical == []

    # Relaxing still searches only what the caller may read: never the exec-only chunk or
    # another KB's chunk.
    widened, _ = await search_relaxing_inferred_filters(
        BACKEND, request(document_types=("contract",)), inferred={"document_types"}
    )
    assert {h.candidate.content for h in widened.lexical} == {"parental leave is sixteen weeks"}


async def test_a_productive_search_is_not_relaxed_and_unknown_names_are_refused() -> None:
    result, relaxed = await search_relaxing_inferred_filters(
        BACKEND, request(document_types=("policy",)), inferred={"document_types"}
    )
    assert relaxed == ()
    assert result.lexical

    with pytest.raises(ValueError, match="not a filter"):
        await search_relaxing_inferred_filters(BACKEND, request(), inferred={"knowledge_base_ids"})


def test_identifiers_are_found_case_insensitively() -> None:
    assert query_identifiers("what does hr-142-b say vs HR-142-B and ISO-27001?") == [
        "HR-142-B",
        "ISO-27001",
    ]
    assert query_identifiers("plain words only") == []


def test_unindexed_filters_are_refused_not_ignored() -> None:
    with pytest.raises(UnsupportedFilter):
        compile_filters(QueryFilters(tags=("benefits",)))
    with pytest.raises(UnsupportedFilter):
        compile_filters(QueryFilters(department="HR"))
    assert compile_filters(QueryFilters()) == []
