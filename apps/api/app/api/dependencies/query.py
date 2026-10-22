"""Query services for the request (T5.3): search services plus the generator factory."""

from typing import Annotated

from fastapi import Depends, Request

from app.api.dependencies.search import SearchServices
from app.rag.orchestration.generation import Generator, PolicyView, build_generator
from app.services.query import QueryDeps


def get_query_deps(request: Request, search: SearchServices) -> QueryDeps:
    """The generator is built per request from settings and the KB's model policy (providers and
    their HTTP clients are cached per configuration), after KB access has been checked."""
    state = request.app.state
    count = search.count_tokens or (lambda text: len(text.split()))

    def generator_for(policy: PolicyView) -> Generator:
        return build_generator(state.settings, state.redis, policy, count)

    return QueryDeps(search=search, generator_for=generator_for)


QueryServices = Annotated[QueryDeps, Depends(get_query_deps)]
