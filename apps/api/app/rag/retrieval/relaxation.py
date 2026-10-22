"""One-time relaxation of inferred filters (plan §17, S24).

Filters a query planner *inferred* (say, a department guessed from the question) are hints: if
they leave nothing, the search runs once more without them. Filters the user set explicitly stay,
and the authorization scope is never touched; relaxation can only widen within what the caller
may already read.
"""

from collections.abc import Collection

from app.providers.search.base import (
    HybridSearchRequest,
    HybridSearchResult,
    QueryFilters,
    SearchBackend,
)


async def search_relaxing_inferred_filters(
    backend: SearchBackend, request: HybridSearchRequest, inferred: Collection[str] = ()
) -> tuple[HybridSearchResult, tuple[str, ...]]:
    """Hybrid search; if it finds nothing, retry once without the inferred filters that were set.
    Returns the result and the names of the filters that were relaxed (empty if none)."""
    unknown = set(inferred) - set(QueryFilters.model_fields)
    if unknown:
        raise ValueError(f"not a filter: {sorted(unknown)}")
    result = await backend.hybrid_search(request)
    if result.dense or result.lexical:
        return result, ()
    defaults = QueryFilters()
    relaxed = tuple(
        sorted(
            name for name in inferred if getattr(request.filters, name) != getattr(defaults, name)
        )
    )
    if not relaxed:
        return result, ()
    filters = request.filters.model_copy(update={name: getattr(defaults, name) for name in relaxed})
    retry = await backend.hybrid_search(request.model_copy(update={"filters": filters}))
    return retry, relaxed
