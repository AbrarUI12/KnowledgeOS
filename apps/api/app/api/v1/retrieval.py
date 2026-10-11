"""Search, query (RAG), query-run and feedback endpoints (contracts from T1.0; implemented in T4.6,
T5.3, T5.4). SSE event payloads: docs/api/sse-events.md."""

import uuid

from fastapi import APIRouter, status
from fastapi.responses import StreamingResponse

from app.api.openapi import STREAM_EVENT_REF
from app.api.v1._stub import ERRORS, OrgIdHeader, stub
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

router = APIRouter(responses=ERRORS)


@router.post("/knowledge-bases/{kb_id}/search", tags=["search"], response_model=SearchResponse)
async def search_knowledge_base(
    org: OrgIdHeader, kb_id: uuid.UUID, body: SearchRequest
) -> SearchResponse:
    """Authorized hybrid search without generation (`query.execute`)."""
    stub("T4.6")


@router.post("/search", tags=["search"], response_model=SearchResponse)
async def search(org: OrgIdHeader, body: MultiSearchRequest) -> SearchResponse:
    """Hybrid search across several KBs the caller may query."""
    stub("T4.6")


@router.post("/knowledge-bases/{kb_id}/query", tags=["query"], response_model=AnswerOut)
async def query_knowledge_base(org: OrgIdHeader, kb_id: uuid.UUID, body: QueryRequest) -> AnswerOut:
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
    org: OrgIdHeader, kb_id: uuid.UUID, body: QueryRequest
) -> StreamingResponse:
    stub("T5.4")


@router.get("/query-runs/{query_run_id}", tags=["query_runs"], response_model=QueryRunOut)
async def get_query_run(org: OrgIdHeader, query_run_id: uuid.UUID) -> QueryRunOut:
    """Run summary; the `debug` section is included only with `retrieval.debug`."""
    stub("T4.6")


@router.post(
    "/query-runs/{query_run_id}/feedback",
    tags=["query_runs"],
    response_model=FeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_feedback(
    org: OrgIdHeader, query_run_id: uuid.UUID, body: FeedbackCreate
) -> FeedbackOut:
    stub("T5.4")
