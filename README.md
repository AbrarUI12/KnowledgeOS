# KnowledgeOS

**Project status: Core implementation completed (November 2026)**

KnowledgeOS is a **multi-tenant, permission-aware Retrieval-Augmented Generation (RAG) platform** for working with organizational knowledge. Users can upload documents to controlled knowledge libraries, search indexed material, and ask questions answered from evidence they are authorized to access, with citations that link back to their source.

The application includes a FastAPI backend, asynchronous ingestion and indexing workers, PostgreSQL-based hybrid retrieval, and a Next.js frontend. It is designed as a full-stack AI engineering project rather than a single-file “chat with PDF” prototype.

> **Deployment note:** The core application is marked complete by its maintainer. A public, end-to-end hosted deployment has **not** been independently verified in this repository update. The public-facing `/demo` route is an interactive preview using fictional data, **not** the live authenticated RAG backend.

## Highlights

- **Multi-tenant access control:** OIDC authentication, organization/member/group management, role-based permissions, PostgreSQL row-level security, and knowledge-base/document access controls.
- **Document ingestion:** Presigned uploads, file validation, malware scanning, Docling-based parsing and OCR, normalization, content-security checks, structure-aware chunking, embeddings, and indexing.
- **Recoverable background processing:** Celery workers and a transactional outbox with job status, retries, checkpoints, and recovery logic.
- **Permission-aware hybrid search:** PostgreSQL full-text search and pgvector similarity search, authorization enforced during retrieval, Reciprocal Rank Fusion (RRF), and reranking.
- **Evidence-grounded answers:** RAG orchestration, server-sent event (SSE) answer streaming, source aliases and citation validation, plus an evidence viewer and answer feedback.
- **Web application:** Workspace navigation, knowledge libraries, document ingestion status, search, Ask, membership/group administration, and an interactive product walkthrough.
- **Quality and security tooling:** pytest, integration testing with Testcontainers, Vitest, TypeScript and Python type checks, linting, GitHub Actions CI, and secret scanning.

## System at a glance

```text
Browser (Next.js / Auth.js)
       |
       +-- OIDC sign-in (Keycloak locally; Auth0 target for staging)
       |
       +-- FastAPI API (permissions, tenant context, RLS)
               |
               +-- PostgreSQL 17 + pgvector / full-text search
               +-- Object storage (MinIO locally; B2 target for staging)
               +-- Transactional outbox -> dispatcher -> Celery workers
               |                                 |
               |                       validate -> scan -> parse/OCR
               |                       -> normalize -> chunk -> embed -> index
               |
               +-- Hybrid retrieval -> rerank -> context -> LLM
                                             |
                                      citations + SSE answer
```

**Security design:** Retrieval incorporates authorization constraints *before* content is sent to a language model; uploaded and retrieved document content is treated as untrusted input. This describes the implemented controls, not a guarantee that every deployment is free of security issues.

## Technology stack

| Layer | Technologies |
| --- | --- |
| Frontend | Next.js 16, React 19, TypeScript, Tailwind CSS 4, Radix UI, TanStack Query, Auth.js |
| Backend | Python 3.12, FastAPI, Pydantic 2, SQLAlchemy 2, Alembic |
| Data and search | PostgreSQL 17, pgvector, `pg_trgm`, full-text search |
| Workers and storage | Celery, Redis, MinIO / S3-compatible object storage |
| Document processing | Docling, OCR, ClamAV |
| AI / RAG | Qwen3-Embedding-0.6B, BAAI/bge-reranker-v2-m3, Ollama or configured external LLM providers |
| Testing and delivery | pytest, Testcontainers, Hypothesis, Vitest, Playwright, Ruff, mypy, ESLint, GitHub Actions |

## Run locally

**Prerequisites:** Git, Docker Desktop (WSL2 on Windows), Python tooling via [uv](https://docs.astral.sh/uv/), Node.js 24, pnpm, GNU Make, and pre-commit.

```bash
git clone https://github.com/AbrarUI12/KnowledgeOS.git
cd KnowledgeOS

make env          # create a local .env from .env.example
# Review .env and configure local credentials, AUTH_SECRET and model settings.
make install      # Python / JavaScript dependencies and git hooks
make up-full      # local backing services + worker, dispatcher and malware scanner
make migrate      # apply database migrations
```

Start the application in **two separate terminals**:

```bash
make api          # http://localhost:8000
```

```bash
make web          # http://localhost:3000
```

The application needs its identity provider and other local services configured for authenticated workflows. For generated answers, configure an LLM provider in `.env` (for example, a local Ollama endpoint); the documented `LLM_PROVIDER=fake` option provides deterministic local/test behavior instead of live model inference. First startup may require model downloads. Keep real API keys and secrets out of version control.

Useful commands:

```bash
make infra-check  # local infrastructure health checks
make test-unit    # backend unit tests
make test-int     # backend integration tests (Docker)
make lint        # backend/frontend lint and formatting checks
make typecheck   # Python / TypeScript checks
make test        # backend and frontend tests
pnpm web:build   # production frontend build
make down        # stop local containers without deleting volumes
```

For deployment configuration, see the [staging setup runbook](docs/runbooks/staging-setup.md). The runbook is a guide; its existence does not imply an active hosted service.

## Preview and documentation

- **Interactive preview:** Open `/demo` on the running web app. Its sample documents and citations are fictional and do not require the live backend.
- **System architecture:** [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- **Security and engineering context:** [docs/AI_CONTEXT.md](docs/AI_CONTEXT.md)
- **Testing strategy:** [docs/TESTING.md](docs/TESTING.md)
- **API and event contracts:** [docs/api/](docs/api/)
- **Design decisions:** [docs/DECISIONS.md](docs/DECISIONS.md) and [docs/adr/](docs/adr/)
- **Original specification and implementation history:** [plan.md](plan.md), [session.md](session.md), [agent.md](agent.md), [docs/TASKS.md](docs/TASKS.md)

The original milestone/task trackers capture the state at the time they were written; they are retained as engineering history and are not a claim about current public hosting availability.

## Repository layout

```text
apps/api/       FastAPI application, migrations, workers, backend tests
apps/web/       Next.js frontend, components, features, frontend tests
packages/       Shared API contracts and generated types
configs/        RAG prompts, policies, profiles
infra/          Local and staging infrastructure / container builds
evals/          Evaluation datasets and scripts
tests/          Cross-stack integration, security, load and E2E suites
scripts/        Setup, demo corpus, smoke checks and utilities
docs/           Architecture, ADRs, API docs, testing, runbooks
```
