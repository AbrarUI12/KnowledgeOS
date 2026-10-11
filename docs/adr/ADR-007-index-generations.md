# ADR-007: Versioned index generations

- **Status:** Accepted
- **Date:** 2026-10-12
- **Related:** plan.md §3 (principles 7, 8, 10), §7.6, §13.2

## Context

Embeddings from different models (or different chunking) are incompatible. Changing the embedding model, chunker or parser in place would corrupt retrieval, cause downtime during re-embedding, and make quality changes impossible to evaluate or roll back.

## Decision

- Every knowledge base has exactly one **active index generation** recording the exact embedding provider/model/dimension (1024 for the first schema), chunker name/config and parser pipeline version.
- Every chunk belongs to a `(document_version, index_generation)`; retrieval always filters to the KB's active generation.
- Changes that affect retrieval create a **candidate** generation, rebuilt side by side from stored canonical artifacts (no re-parsing unless the parser changed), with dual-write for new documents during the build.
- A candidate is activated only after offline evaluation and security regression pass, via an **atomic switch** of `active_index_generation_id`. The previous generation is retained for instant **rollback**, then garbage-collected.

## Consequences

- Zero-downtime retrieval changes with evaluation gating and rollback.
- Temporary storage overhead while two generations coexist (constrained on the free Neon tier; large rebuilds run locally).
- All retrieval, query embedding and evaluation code must be generation-aware.

## Alternatives considered

- **Re-embed in place** — rejected: downtime, mixed vectors, no rollback.
- **Separate tables per model** — rejected: schema churn; generations achieve the same with one schema.
