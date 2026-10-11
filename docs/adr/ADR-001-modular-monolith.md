# ADR-001: Modular monolith

- **Status:** Accepted
- **Date:** 2026-10-12
- **Related:** plan.md §3 (principle 1), §4.1, §6

## Context

KnowledgeOS has many concerns (identity, ingestion, retrieval, generation, evaluation, connectors) and is built by a very small team on a $0 budget. A microservice split would multiply deployments, network failure modes, observability work and hosting cost before any of it is justified by load or team structure.

## Decision

Build **one backend codebase** (`apps/api`): a FastAPI application plus Celery workers that share the same packages, database and configuration. Internal boundaries are enforced as Python packages (`auth`, `ingestion`, `rag/*`, `providers/*`, `services`, …), not as network services. Process roles (api, worker, dispatcher, scheduler) are separate entry points over the same image. The frontend (`apps/web`) is a separate app in the same monorepo.

## Consequences

- One deploy artifact, one migration history, transactional consistency across domains (needed for the outbox, ADR-005).
- Module boundaries depend on discipline: providers are only obtained through interfaces/registries, and an import-guard test (Session 53) keeps concrete providers out of feature code.
- If one area later needs independent scaling (e.g. local model serving), it can be extracted behind its existing interface.

## Alternatives considered

- **Microservices from day one** — rejected: operational cost and complexity with no current benefit.
- **Separate repositories for api/web** — rejected: harder atomic changes and contract syncing (the OpenAPI client is generated in-repo).
