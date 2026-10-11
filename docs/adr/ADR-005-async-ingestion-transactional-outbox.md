# ADR-005: Async ingestion with a transactional outbox

- **Status:** Accepted
- **Date:** 2026-10-12
- **Related:** plan.md §3 (principle 11), §14, §34.4

## Context

Parsing, OCR, chunking and embedding take seconds to minutes and must never run inside HTTP requests. Naively committing a database change and then publishing to a queue loses work if the publish fails after commit, and duplicates work if a worker dies mid-task.

## Decision

- HTTP handlers only change state. Background work is requested by inserting an **`outbox_events` row in the same transaction** as the business change.
- A **dispatcher** process claims unpublished events (`FOR UPDATE SKIP LOCKED`), publishes them to **Celery** (Redis broker) and marks them published, with backoff on failure.
- Ingestion jobs follow an explicit **state machine** stored in PostgreSQL (the source of truth for progress, never Celery state). Each stage is **idempotent** and checkpointed; a job lease plus advisory locks prevent concurrent processing; heartbeats and a reconciliation task recover stuck or orphaned jobs.
- Celery: `acks_late`, `reject_on_worker_lost`, prefetch 1, bounded retries with exponential backoff and jitter.

## Consequences

- No "committed but never processed" gap; duplicate deliveries are harmless.
- Redis is replaceable/non-authoritative: losing it loses no durable state (important for the free deployment, ADR-008).
- More moving parts (dispatcher, beat) and the discipline of idempotent stages.

## Alternatives considered

- **Publish directly after commit** — rejected: lost-work window.
- **Synchronous ingestion** — rejected: timeouts, no recovery.
- **Dedicated workflow engine (Temporal etc.)** — rejected for now: extra infrastructure; revisit if workflows grow complex.
