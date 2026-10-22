"""Search, query (RAG), query-run and feedback endpoints (contracts from T1.0; implemented in T4.6,
T5.3, T5.4). SSE event payloads: docs/api/sse-events.md."""

import uuid
from typing import Annotated

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.search import SearchServices
from app.api.dependencies.tenancy import OrgContext, require_permission
from app.api.openapi import STREAM_EVENT_REF
from app.api.v1._stub import ERRORS, OrgIdHeader, stub
from app.auth.authorization import RequestContext
from app.auth.permissions import Permission
from app.db.session import DbSession
from app.domain.schemas.retrieval import (
    AnswerOut,
    FeedbackCreate,
    FeedbackOut,
    MultiSearchRequest,
    QueryRequest,
    QueryRunOut,
    SearchRequest,
    SearchResponse,
)
from app.services import evidence
from app.services import search as search_service

router = APIRouter(responses=ERRORS)
QueryExecute = Annotated[RequestContext, require_permission(Permission.QUERY_EXECUTE)]


@router.post("/knowledge-bases/{kb_id}/search", tags=["search"], response_model=SearchResponse)
async def search_knowledge_base(
    org: OrgIdHeader,
    ctx: QueryExecute,
    session: DbSession,
    services: SearchServices,
    kb_id: uuid.UUID,
    body: SearchRequest,
) -> SearchResponse:
    """Authorized hybrid search without generation (`query.execute`). 404 if the KB isn't
    visible, 403 if it's visible but its content isn't readable. `debug=true` (needs
    `retrieval.debug`) adds the run's branch ranks and scores."""
    return await search_service.search(session, ctx, services, [kb_id], body)


@router.post("/search", tags=["search"], response_model=SearchResponse)
async def search(
    org: OrgIdHeader,
    ctx: QueryExecute,
    session: DbSession,
    services: SearchServices,
    body: MultiSearchRequest,
) -> SearchResponse:
    """Hybrid search across several KBs the caller may query (each checked as above)."""
    return await search_service.search(session, ctx, services, body.knowledge_base_ids, body)


@router.post("/knowledge-bases/{kb_id}/query", tags=["query"], response_model=AnswerOut)
async def query_knowledge_base(
    org: OrgIdHeader, ctx: OrgContext, kb_id: uuid.UUID, body: QueryRequest
) -> AnswerOut:
    """Grounded answer with validated citations (non-streaming)."""
    stub("T5.3")


@router.post(
    "/knowledge-bases/{kb_id}/query/stream",
    tags=["query"],
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {"schema": {"$ref": STREAM_EVENT_REF}}},
            "description": "SSE stream: meta, stage, sources, answer_delta, citation, done, error "
            "(docs/api/sse-events.md)",
        }
    },
)
async def query_knowledge_base_stream(
    org: OrgIdHeader, ctx: OrgContext, kb_id: uuid.UUID, body: QueryRequest
) -> StreamingResponse:
    stub("T5.4")


@router.get("/query-runs/{query_run_id}", tags=["query_runs"], response_model=QueryRunOut)
async def get_query_run(
    org: OrgIdHeader, ctx: OrgContext, session: DbSession, query_run_id: uuid.UUID
) -> QueryRunOut:
    """Run summary for the person who ran it; anyone else gets 404 unless they hold
    `retrieval.debug`, which also adds the `debug` section (hits the viewer can't read hidden)."""
    return await search_service.get_query_run(session, ctx, query_run_id)


@router.post(
    "/query-runs/{query_run_id}/feedback",
    tags=["query_runs"],
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_feedback(
    org: OrgIdHeader,
    ctx: OrgContext,
    session: DbSession,
    query_run_id: uuid.UUID,
    body: FeedbackCreate,
) -> FeedbackOut:
    """Thumbs up/down with an optional reason code and comment on your own run; giving feedback
    again replaces it."""
    return await evidence.give_feedback(session, ctx, query_run_id, body)
