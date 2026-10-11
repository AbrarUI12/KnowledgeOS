# System Architecture

> Entry point for the architecture. The full target spec is `plan.md`; decisions and their reasons are in `docs/DECISIONS.md`. Diagrams: [`docs/architecture/overview.md`](architecture/overview.md). Frontend system: [`docs/architecture/frontend-design.md`](architecture/frontend-design.md).

## Overview

KnowledgeOS is a **modular monolith** (ADR-001): one Python codebase (`apps/api`) serving the HTTP API and running background workers, one Next.js app (`apps/web`), and PostgreSQL as the durable source of truth for data, permissions, job state and search (ADR-002).

```text
User ─► Frontend (Next.js) ─► API (FastAPI routes) ─► Services ─► Data layer (SQLAlchemy, RLS) ─► PostgreSQL
                                        │                  └─► Providers (interfaces) ─► storage / models / search / IdP
                                        └─► Outbox ─► Dispatcher ─► Celery workers ─► ingestion stages
```

## Main components

### Frontend (`apps/web`)
Responsibilities: UI, interaction, client state, calling the API with the user's bearer token, rendering streamed answers and evidence.
Must not contain: business or authorization rules (the UI may *hide* actions, the backend *decides*), direct database access, raw colors (tokens only).
Structure: `app/` routes, `components/primitives|shell|motion|command|feedback`, `features/<domain>`, `lib/api|auth|events|motion|permissions`.

### API layer (`app/api`)
Responsibilities: authentication (`api/dependencies/auth.py`), tenant context resolution, request validation (Pydantic schemas in `app/domain`), response formatting with the error envelope (`api/errors.py`), routing under `/v1` (`api/v1/router.py`), request IDs (`api/middleware.py`).
Must not contain substantial business logic. Routes validate, call one service function and translate errors.

### Service layer (`app/services`, plus domain packages `app/ingestion`, `app/rag`)
Responsibilities: business rules, orchestration, transaction-level operations, audit events, outbox events.
Examples: org/member management, upload completion (document + version + job + outbox in one transaction), query orchestration (search → rerank → pack → generate → validate).

### Data layer (`app/db`)
Responsibilities: engine/session (`db/session.py`, one transaction per request), ORM models (`db/models/`), migrations (`apps/api/migrations/`, **Claude only**), grant helpers (`db/migration_helpers.py`).
Conventions (D-012): UUIDv7 keys, `timestamptz`, text + CHECK instead of enums, composite `(x_id, organization_id)` FKs, grants inside migrations.

### Providers (`app/providers/*`)
Every external capability behind a Protocol (ADR-006): `storage` (S3/MinIO/B2), `scanning` (ClamAV), `identity` (OIDC/JWKS), `embeddings`, `rerankers`, `llm` (OpenAI-compatible: Ollama/Groq/Gemini), `search` (Postgres hybrid). Each declares whether it is **external**. Feature code never imports a concrete provider (a router/registry enforces model policy, Session 53).

### Workers (`app/workers`)
Celery (Redis broker) + an outbox dispatcher + beat scheduler (ADR-005). Ingestion is an explicit state machine with idempotent, checkpointed stages; progress lives in Postgres, never in Celery state.

### Database
PostgreSQL 17 with `vector` (HNSW, 1024-d) and `pg_trgm`. Local: Docker (`:5433`); deployed: Neon. Roles: `knowledgeos_owner` (migrations), `knowledgeos_app` (runtime, `NOBYPASSRLS`, owns nothing), `knowledgeos_dispatcher` (outbox only).

## Data flows

**Upload & ingestion:** browser → `POST /uploads` (presigned PUT to the quarantine bucket) → browser uploads directly → `POST /uploads/{id}/complete` (HEAD verify; document + version + job + outbox in one transaction) → dispatcher → worker stages: validate → malware scan → promote to trusted bucket → parse (Docling, canonical JSON artifact) → normalize → content-security scan → chunk → embed → index (tsvector + ACL tokens) → verify → READY.

**Query:** authenticate → resolve org + KB access → load active index generation + RAG profile + model policy → normalize → dense + lexical search **with the authorization predicate in SQL** → RRF fusion → rerank → token-budget packing with `[S#]` aliases → generation (evidence delimited as untrusted) → citation validation → SSE stream. The DB transaction closes **before** generation starts.

## Authentication
OIDC (ADR-003). The API verifies JWT signature (cached JWKS, RS256/ES256 allowlist), `iss`, `aud`, `exp`/`nbf`, `sub`; users are provisioned just in time by `(issuer, sub)`. The browser holds a short-lived access token in memory (Auth.js session) and calls the API directly with `Authorization: Bearer`. The API uses no cookies, so there's no CSRF surface. API keys (hashed, scoped) arrive in Session 55.

## Authorization
Three layers, all fail-closed (ADR-004):
1. **Permissions:** role → permission strings (`app/auth/permissions.py`); routes declare `require_permission(...)`.
2. **Tenant RLS:** every tenant table has `organization_id` + forced RLS against transaction-local `app.organization_id` (`set_config(..., true)`, never session `SET`). Cross-org IDs return 404.
3. **Within-tenant ACLs:** KB/document allow-lists (documents may only narrow a KB). They are materialized onto every chunk as `access_principals` tokens (`user:…`, `group:…`, `role:…`, `org:…`) and enforced inside the retrieval SQL, never filtered after ranking.

## Error handling
One JSON envelope `{"error": {code, message, request_id, details}}` with stable codes ([`docs/api/errors.md`](api/errors.md)). Validation errors never echo input. 500s never leak exception text. Logs are structured JSON with secret redaction and the request ID.

## Background jobs
Transactional outbox → dispatcher (`FOR UPDATE SKIP LOCKED`) → Celery (`acks_late`, prefetch 1, bounded retries with jitter) → state machine with leases, heartbeats, checkpoints and a reconciliation sweeper. Duplicate deliveries are harmless.

## External integrations
| Integration | Interface | Local | Deployed |
|---|---|---|---|
| Identity | `providers/identity` | Keycloak | Auth0 |
| Object storage | `providers/storage` | MinIO | Backblaze B2 |
| Malware scan | `providers/scanning` | ClamAV container | ClamAV in image |
| Embeddings / reranker | `providers/embeddings`, `providers/rerankers` | in-process open models (CUDA ok) | in-process, CPU |
| Generation | `providers/llm` (OpenAI-compatible) | Ollama | Groq → Gemini free tiers |
| Tracing (later) | OTel / Langfuse | otel-lgtm container | Grafana Cloud / Langfuse Cloud |

## Deployment
ADR-008: Vercel (web) + one Hugging Face Docker Space running api, workers, dispatcher, beat, Redis and clamd under supervisord + Neon + B2 + Auth0. CI on GitHub Actions; images on GHCR. Environments: local → staging (M1, Session 33) → production (Session 62).
