# ADR-002: PostgreSQL + pgvector first search

- **Status:** Accepted
- **Date:** 2026-10-12
- **Related:** plan.md §3 (principle 6), §8.1, §8.4, §18, §36.3

## Context

Retrieval needs dense vectors, lexical (full-text) search, trigram matching for identifiers, and **authorization filters applied before ranking**. Dedicated search engines (OpenSearch, Qdrant, Weaviate, Vespa) add infrastructure, cost and a second consistency boundary between relational permissions and search data.

## Decision

Use **PostgreSQL** for relational data **and** retrieval:

- `pgvector` HNSW (cosine) for dense retrieval, with iterative scans for filtered queries;
- `tsvector`/`websearch_to_tsquery`/`ts_rank_cd` for lexical retrieval;
- `pg_trgm` for identifiers and fuzzy fallback;
- authorization metadata (`organization_id`, active generation/version, `access_principals`) on every chunk row, filtered in the same SQL statement.

All retrieval goes through a `SearchBackend` interface so the implementation can change later.

## Consequences

- Authorization and content live in one transactional store; ACL changes and searches see consistent data.
- Hosted on free Neon (pgvector included) — no extra service to run.
- Filtered approximate search can lose recall; this is measured (Session 24 and 58) and tuned (`ef_search`, iterative scan).
- Migration to a dedicated engine happens only when benchmarks justify it, behind `SearchBackend`.

## Alternatives considered

- **Dedicated vector DB + separate lexical engine** — rejected for now: cost, ops and post-filtering risks.
- **Vector-only retrieval** — rejected: misses exact identifiers such as `HR-142-B`.
