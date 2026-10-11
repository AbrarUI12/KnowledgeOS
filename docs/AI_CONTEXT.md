# KnowledgeOS — AI Context

> **Shared source of truth for every coding agent (Claude Code, Codex, Cline) and every human.**
> Read this first. It is deliberately short; it points to the detailed documents instead of repeating them.

## Project

**KnowledgeOS** is a multi-tenant, permission-aware **Retrieval-Augmented Generation (RAG)** platform. Organizations upload or connect their documents, control who can see what, and ask questions that are answered **only from evidence the asking user is allowed to read**, with verifiable citations. It is a portfolio-grade, production-style system, not a "chat with PDF" demo.

**Budget: $0.** Every service is a free tier or an open model (see `docs/DECISIONS.md` D-001).

## Current milestone

**M1: first live deployment (staging)**, i.e. session.md Sessions 07–33 / Sprints 1–6. The work is split between three agents in [`docs/TASKS.md`](TASKS.md).

## Where things are documented

| Need | Read |
|---|---|
| What to work on now, who owns what, task status | [`docs/TASKS.md`](TASKS.md) |
| How the three agents cooperate (worktrees, review, merge, communication, prompts) | [`docs/AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md) |
| System architecture and layering rules | [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) |
| Why things are the way they are | [`docs/DECISIONS.md`](DECISIONS.md) + [`docs/adr/`](adr/README.md) |
| How to test | [`docs/TESTING.md`](TESTING.md) |
| Detailed spec of each work item ("Tasks" and "Done when") | [`session.md`](../session.md), the session referenced by the task |
| Target architecture and product spec (never edited) | [`plan.md`](../plan.md), only the `§` sections a task references |
| Project status, gates, setup commands, open issues, env-var register | [`agent.md`](../agent.md) |
| Frontend visual system | [`docs/architecture/frontend-design.md`](architecture/frontend-design.md) |
| API error codes | [`docs/api/errors.md`](api/errors.md) |

## Technology stack

| Layer | Local development | Deployed ($0) |
|---|---|---|
| Frontend | Next.js 16 (App Router), React 19, TypeScript strict, Tailwind 4, shadcn/Radix restyled, Motion, TanStack Query, Auth.js | Vercel Hobby |
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2 async, Alembic, structlog, Celery | One Hugging Face Docker Space (supervisord) |
| Database | PostgreSQL 17 + pgvector + pg_trgm (`localhost:5433`) | Neon Free |
| Queue/cache | Redis 7 (`localhost:6380`) | in-container Redis |
| Object storage | MinIO (`localhost:9000`) | Backblaze B2 |
| Identity | Keycloak (`localhost:8080`, realm `knowledgeos`) | Auth0 Free |
| Documents | Docling + OCR, ClamAV | same |
| Models | Qwen3-Embedding-0.6B (1024-d), bge-reranker-v2-m3, Ollama for generation | same embed/rerank in-process; Groq → Gemini free tiers |
| Quality | Ruff, mypy strict, pytest + Testcontainers + Hypothesis, ESLint, Prettier, Vitest, Playwright, axe-core | GitHub Actions CI |

## Architecture in one picture

```text
Browser ──► Next.js web ──► (OIDC login: Keycloak / Auth0)
   │
   └──bearer token / SSE──► FastAPI API ──► services ──► PostgreSQL (RLS on every tenant table)
                                │                    └─► providers (storage, models, search) via interfaces
                                └─► outbox row (same txn) ──► dispatcher ──► Celery workers
                                                                   └─► validate → scan → parse → chunk → embed → index
```

Details and rules: [`docs/ARCHITECTURE.md`](ARCHITECTURE.md).

## Engineering rules (non-negotiable)

1. **Tenant isolation first.** Every tenant-scoped table has `organization_id` + forced RLS. Cross-org access returns 404. Fail closed.
2. **Authorize before generation.** Authorization filters are part of the retrieval query; nothing unauthorized ever reaches a model.
3. **Retrieved document text is untrusted data**, never instructions.
4. **Providers only through interfaces** (`app/providers/*`). Model IDs live in config. Never silently substitute an embedding model.
5. **No business logic in route handlers.** Routes validate and delegate to services.
6. **Typed schemas** for every API payload (Pydantic / Zod); generated TS client for the frontend.
7. **New behaviour needs tests.** Never delete, skip or weaken a test to make CI pass.
8. **Schema changes need a migration**, and only Claude writes migrations (see AGENT_WORKFLOW).
9. **No silent dependencies.** Justify every new package in the PR.
10. **Small, focused changes.** No unrelated refactors or formatting churn. Stay inside your task and your owned files.
11. **No secrets in git or docs.** Env var *names* only.
12. **Frontend uses design tokens only** (no raw colors; enforced by lint) and must stay accessible (keyboard, contrast, reduced motion).

## Commands

```bash
make install            # uv sync + pnpm install + pre-commit install
make up | up-full       # local Docker stack (core | + ClamAV); make infra-check to verify
make api [API_PORT=…]   # FastAPI with reload (default 8000)
make web [WEB_PORT=…]   # Next.js dev (default 3000)
make migrate            # alembic upgrade head
make lint typecheck test
make test-unit | test-int
pnpm web:test           # frontend unit tests only
```

Windows notes: Docker Desktop (WSL2) must be running. Celery, Docling, OCR and ClamAV run only in Linux containers. Keep repositories at short paths (Windows MAX_PATH).

## Definition of done (every task)

1. Implementation finished and inside the task's scope and owned paths.
2. Tests written with the code; `make lint typecheck test` green locally and in CI.
3. Migrations included (by Claude) if the schema changed.
4. API changes reflected in OpenAPI and the regenerated TS client.
5. Docs updated if behaviour or setup changed; new env var names in `.env.example` and agent.md §11.
6. Cross-agent review posted with no open BLOCKER/HIGH findings.
7. `docs/TASKS.md` status and the agent's block in `agent.md` updated; completion report in the PR.
