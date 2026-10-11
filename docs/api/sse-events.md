# SSE events: `POST /v1/knowledge-bases/{kb_id}/query/stream`

> Contract from T1.0. Server implementation: Claude T5.4. Client (stream reducer): Codex T5.5.
> Payload schemas are the `Stream*` models in `apps/api/app/domain/schemas/retrieval.py`. They're published in `packages/contracts/openapi.json` as the discriminated union `StreamEvent` (`{event, data}`) on the stream response, so the TS client can generate types for the reducer. Change them only through a `contract-change` PR.

## Transport

- Request: `POST` with JSON body `QueryRequest`, headers `Authorization: Bearer <token>`, `X-Organization-Id: <uuid>`, `Accept: text/event-stream`. `EventSource` can't send headers or POST, so the client uses a fetch-based reader (`@microsoft/fetch-event-source` or equivalent).
- Response: `200` with `Content-Type: text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`. Errors **before** the stream starts (auth, validation, KB not found) use normal HTTP status codes and the JSON error envelope.
- Frames: `event: <name>` + `data: <one-line JSON>` + blank line. Comment lines (`: keep-alive`) every ~15 s; ignore them.
- Cancellation: closing the connection cancels generation server-side; the run is recorded as `cancelled`.

## Event order

```text
meta
stage (retrieval.started)
stage (retrieval.completed)
stage (rerank.started)          ┐ omitted when reranking is skipped
stage (rerank.completed)        ┘
sources                          (omitted when the server abstains before generation)
stage (generation.started)       (omitted on early abstention)
answer_delta …                   (0..n)
citation …                       (0..n, may arrive interleaved with answer_delta and after it)
done | error                     (exactly one, always last)
```

Clients must tolerate missing optional events and must not assume a fixed number of `answer_delta` events.

## Events

| Event | Payload model | Fields | Notes |
|---|---|---|---|
| `meta` | `StreamMeta` | `query_run_id`, `trace_id?`, `profile?`, `model?` | First event. Use `query_run_id` for feedback and the debugger link |
| `stage` | `StreamStage` | `stage` (`retrieval.started` · `retrieval.completed` · `rerank.started` · `rerank.completed` · `generation.started`), `candidates?`, `elapsed_ms?` | System status only, never model reasoning. `candidates` is set on `*.completed` |
| `sources` | `StreamSources` | `sources: SourceAlias[]` | Alias metadata (`S1`…) from storage. Citations become clickable once this arrives |
| `answer_delta` | `StreamAnswerDelta` | `text` | Markdown, batched at sentence/block boundaries (never per character). Append in order |
| `citation` | `StreamCitation` | `alias`, `chunk_id?`, `valid` | Validation result for an alias in the answer. `valid: false` = remove/flag that marker in place; don't re-render the whole answer |
| `done` | `StreamDone` | `abstained`, `abstain_reason?`, `evidence_status`, `conflicts[]`, `usage`, `timing`, `degraded` | Terminal. `evidence_status` ∈ strong · partial · conflicting · insufficient · source_unavailable · retrieval_degraded |
| `error` | `StreamError` | `code`, `message` | Terminal. Safe message only, no stack traces. Codes follow `docs/api/errors.md` (e.g. `generation_failed`, `citations_invalid`, `rate_limited`) |

## Example

```text
event: meta
data: {"query_run_id":"0192a8f4-77c1-7c3e-9d1a-5b2e4f6a7b8c","trace_id":"4bf92f35","profile":"default-hybrid-v1","model":"llama-3.3-70b"}

event: stage
data: {"stage":"retrieval.completed","candidates":28,"elapsed_ms":212.4}

event: sources
data: {"sources":[{"alias":"S1","chunk_id":"…","document_id":"…","document_version_id":"…","title":"Employee Handbook 2026","version_number":3,"section_path":["Leave","Parental leave"],"page_start":14,"page_end":14,"source_url":null,"content_hash":"…"}]}

event: answer_delta
data: {"text":"Primary caregivers get **16 weeks** of paid parental leave [S1]. "}

event: citation
data: {"alias":"S1","chunk_id":"…","valid":true}

event: done
data: {"abstained":false,"abstain_reason":null,"evidence_status":"strong","conflicts":[],"usage":{"input_tokens":2140,"output_tokens":96,"estimated":false},"timing":{"retrieval_ms":212.4,"rerank_ms":640.1,"generation_ms":1830.0,"total_ms":2702.9},"degraded":false}
```

## Client state machine (plan §27.26)

Map events to reducer actions: `meta` → `query.accepted`; `stage` → `retrieval.*` / `rerank.*` / `generation.started`; `sources` → sources available; `answer_delta` → `answer.delta`; `citation` → `citation.available`; `done` → `answer.completed`; `error` → `answer.failed`; user abort → `query.cancelled`.
