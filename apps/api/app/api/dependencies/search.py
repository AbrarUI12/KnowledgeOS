"""Search services for the request: the PostgreSQL backend and the query embedder (T4.6)."""

from typing import Annotated

from fastapi import Depends, Request

from app.ingestion.stages import embedding_provider
from app.providers.search.postgres import PostgresSearchBackend
from app.rag.orchestration.providers import context_token_counter, reranker_provider
from app.services.search import SearchDeps


def get_search_deps(request: Request) -> SearchDeps:
    """The backend runs its branches on its own tenant transactions (two connections). The query
    embedder is the process-wide provider of the configured model (loaded once), or None when its
    library isn't installed, in which case search runs lexically and says so (`degraded`). The
    reranker and the context token counter serve the debug view's RERANK and CONTEXT steps."""
    state = request.app.state
    return SearchDeps(
        backend=PostgresSearchBackend(state.sessionmaker),
        embedder=embedding_provider(state.settings),
        settings=state.settings,
        reranker=reranker_provider(state.settings),
        count_tokens=context_token_counter(state.settings),
    )


SearchServices = Annotated[SearchDeps, Depends(get_search_deps)]
