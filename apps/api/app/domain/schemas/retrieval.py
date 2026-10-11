"""API schemas: search, query, query runs, debug, feedback, SSE events (T1.0; implemented
T4.6/T5.3/T5.4).

SSE event payloads are documented in docs/api/sse-events.md; the `Stream*` models below are the
source of truth for that document.
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, RootModel

from app.domain.enums import EvidenceStatus, FeedbackRating, MatchType
from app.ingestion.canonical import SourceLocation
from app.providers.search.base import QueryFilters
from app.rag.types import SourceAlias, Usage

# ----------------------------------------------------------------------------- search


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    filters: QueryFilters = QueryFilters()
    limit: int = Field(default=20, ge=1, le=100)
    debug: bool = Field(default=False, description="Include branch ranks/scores (retrieval.debug)")


class MultiSearchRequest(SearchRequest):
    knowledge_base_ids: list[uuid.UUID] = Field(min_length=1, max_length=50)


class SearchHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_version_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    title: str
    section_path: list[str]
    snippet: str = Field(description="Plain text; matched terms wrapped in «…» markers")
    match_type: MatchType
    location: SourceLocation
    score: float = Field(description="Fused score (relative within one response only)")


class SearchResponse(BaseModel):
    query_run_id: uuid.UUID
    hits: list[SearchHit]
    degraded: bool = False


# ----------------------------------------------------------------------------- query (RAG)


class QueryScope(BaseModel):
    """Optional narrowing within the KB in the path (plan §27.7.1 scope control)."""

    document_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None
    scope: QueryScope = QueryScope()
    filters: QueryFilters = QueryFilters()


class Citation(BaseModel):
    alias: str = Field(pattern=r"^S[1-9][0-9]*$")
    chunk_id: uuid.UUID
    valid: bool = True


class ConflictNote(BaseModel):
    topic: str
    aliases: list[str] = Field(min_length=2)
    description: str


class Timing(BaseModel):
    retrieval_ms: float | None = None
    rerank_ms: float | None = None
    generation_ms: float | None = None
    total_ms: float | None = None


class AnswerOut(BaseModel):
    query_run_id: uuid.UUID
    answer_markdown: str
    abstained: bool
    abstain_reason: str | None = None
    evidence_status: EvidenceStatus
    sources: list[SourceAlias]
    citations: list[Citation]
    conflicts: list[ConflictNote] = Field(default_factory=list)
    usage: Usage = Usage()
    timing: Timing = Timing()
    degraded: bool = False


class FeedbackCreate(BaseModel):
    rating: FeedbackRating
    reason_code: str | None = Field(default=None, max_length=64)
    comment: str | None = Field(default=None, max_length=4000)


class FeedbackOut(BaseModel):
    id: uuid.UUID
    created_at: datetime


# ----------------------------------------------------------------------------- query runs / debug


class DebugHit(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    title: str
    dense_rank: int | None = None
    dense_score: float | None = None
    lexical_rank: int | None = None
    lexical_score: float | None = None
    fused_score: float | None = None
    rerank_score: float | None = None
    selected_for_context: bool = False


class QueryRunOut(BaseModel):
    """Basic view for everyone who can see the run; `debug` only with retrieval.debug."""

    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    query_type: str | None = None
    status: str
    created_at: datetime
    timing: Timing = Timing()
    trace_id: str | None = None
    debug: "QueryRunDebug | None" = None


class QueryRunDebug(BaseModel):
    rag_profile_version: str | None
    index_generation_id: uuid.UUID | None
    embedding_model: str | None
    reranker_model: str | None
    generation_model: str | None
    filters: QueryFilters
    principal_summary: str = Field(
        description="e.g. '3 groups, role member'. Never lists unauthorized documents"
    )
    hits: list[DebugHit]
    degraded: list[str] = Field(default_factory=list)


QueryRunOut.model_rebuild()


# ----------------------------------------------------------------------------- SSE events

StageName = Literal[
    "retrieval.started",
    "retrieval.completed",
    "rerank.started",
    "rerank.completed",
    "generation.started",
]


class StreamMeta(BaseModel):
    query_run_id: uuid.UUID
    trace_id: str | None = None
    profile: str | None = None
    model: str | None = None


class StreamStage(BaseModel):
    stage: StageName
    candidates: int | None = None
    elapsed_ms: float | None = None


class StreamSources(BaseModel):
    sources: list[SourceAlias]


class StreamAnswerDelta(BaseModel):
    text: str = Field(description="One or more complete sentences/blocks, never single characters")


class StreamCitation(BaseModel):
    alias: str
    chunk_id: uuid.UUID | None = None
    valid: bool


class StreamDone(BaseModel):
    abstained: bool
    abstain_reason: str | None = None
    evidence_status: EvidenceStatus
    conflicts: list[ConflictNote] = Field(default_factory=list)
    usage: Usage = Usage()
    timing: Timing = Timing()
    degraded: bool = False


class StreamError(BaseModel):
    code: str
    message: str


# One SSE frame = `event: <name>` + `data: <payload JSON>`. These envelopes exist so the event
# vocabulary is part of the OpenAPI contract (components "StreamEvent*"); the wire format sends
# `event` as the SSE event name and `data` as the JSON payload.


class StreamMetaEvent(BaseModel):
    event: Literal["meta"]
    data: StreamMeta


class StreamStageEvent(BaseModel):
    event: Literal["stage"]
    data: StreamStage


class StreamSourcesEvent(BaseModel):
    event: Literal["sources"]
    data: StreamSources


class StreamAnswerDeltaEvent(BaseModel):
    event: Literal["answer_delta"]
    data: StreamAnswerDelta


class StreamCitationEvent(BaseModel):
    event: Literal["citation"]
    data: StreamCitation


class StreamDoneEvent(BaseModel):
    event: Literal["done"]
    data: StreamDone


class StreamErrorEvent(BaseModel):
    event: Literal["error"]
    data: StreamError


class StreamEvent(
    RootModel[
        Annotated[
            StreamMetaEvent
            | StreamStageEvent
            | StreamSourcesEvent
            | StreamAnswerDeltaEvent
            | StreamCitationEvent
            | StreamDoneEvent
            | StreamErrorEvent,
            Field(discriminator="event"),
        ]
    ]
):
    """Any event of `POST /v1/knowledge-bases/{kb_id}/query/stream` (docs/api/sse-events.md)."""
