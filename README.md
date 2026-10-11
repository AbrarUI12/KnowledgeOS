# KnowledgeOS

A multi-tenant, permission-aware **Retrieval-Augmented Generation (RAG) platform**. Organizations connect their documents, control who can see what, and ask questions that are answered **only from evidence the user is allowed to read**, with verifiable citations.

> **Status:** early development (Sprint 0: Foundation). Not usable yet. Progress is tracked in [`agent.md`](agent.md).

## Documents

| File | What it is |
|---|---|
| [`plan.md`](plan.md) | The full architecture and product specification |
| [`session.md`](session.md) | The build plan: 65 sessions in 17 sprints, from bootstrap to production |
| [`agent.md`](agent.md) | Live progress and handoff log: read this first |

## Stack

FastAPI · SQLAlchemy 2 · PostgreSQL + pgvector · Celery + Redis · Docling · Next.js · TypeScript · Tailwind CSS · Motion. The project runs entirely on free tiers and open models (see `session.md` §3).

## Development (work in progress)

Prerequisites: Git, Docker Desktop (WSL2 on Windows), [uv](https://docs.astral.sh/uv/), Node.js LTS, pnpm, GNU make, pre-commit.

```bash
make install     # backend + frontend dependencies, git hooks
make lint        # Ruff, ESLint, Prettier
make typecheck   # mypy (strict), tsc
make test        # pytest, Vitest
make api         # API on http://localhost:8000  (GET /health/live)
make web         # Web on http://localhost:3000
```

## Repository layout

```text
apps/api      FastAPI backend and workers
apps/web      Next.js frontend
packages/     Shared contracts (generated API types)
evals/        Evaluation datasets, rubrics and experiments
tests/        Cross-stack integration, security, load and E2E tests
infra/        Docker, Compose, Terraform, monitoring
configs/      Prompts, RAG profiles, policies
docs/         ADRs, architecture, threat model, runbooks
```
