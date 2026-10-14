# ADR-004: Tenant isolation with Row-Level Security

- **Status:** Accepted
- **Date:** 2026-10-12
- **Related:** plan.md §3 (principles 2, 9), §7.1, §8.2, §8.3

## Context

A cross-tenant leak is the worst failure this product can have. Application-level `WHERE organization_id = …` checks are necessary but a single forgotten filter would leak data.

## Decision

Two independent layers:

1. **Application layer:** every request resolves a `RequestContext` (user, organization, role, permissions, principal tokens) and services check permissions explicitly.
2. **Database layer:** every tenant-scoped table has an explicit `organization_id` and PostgreSQL **RLS enabled and forced**, with policies comparing it to the transaction-local setting `app.organization_id`.

Rules:

- The runtime connects as `knowledgeos_app`: `NOSUPERUSER`, `NOBYPASSRLS`, owns no tables. Migrations run as `knowledgeos_owner`. `/health/ready` and the infra check assert the runtime role cannot bypass RLS.
- Context is set with `set_config('app.organization_id', …, true)` **inside each transaction**, never session-level `SET` (pooled connections would leak it).
- Missing context ⇒ `current_setting(..., true)` is NULL ⇒ zero rows (**fail closed**).
- The outbox dispatcher uses `knowledgeos_dispatcher` with an RLS policy limited to `outbox_events` (Session 16).
- A meta-test (Session 12) fails if any table with `organization_id` lacks forced RLS.
- Cross-org resource IDs return **404**, not 403, to avoid revealing existence.

## Consequences

- A missing application filter cannot leak another tenant's rows.
- Every DB access must happen inside a transaction with context set; workers use an explicit `tenant_session(org_id)` helper.
- Within-tenant ACLs (KB/document) are still enforced by the application and by chunk `access_principals` (ADR-002).

## Alternatives considered

- **Application filters only** — rejected: one bug away from a leak.
- **Schema or database per tenant** — rejected: migration/ops cost and poor fit for free hosting.

## Dispatcher exception (Session 16, T3.1)

The outbox dispatcher publishes events for every organization, so it is the one runtime component with cross-tenant access, scoped as narrowly as possible:

- it connects as its own role, `knowledgeos_dispatcher` (`NOBYPASSRLS`, owns nothing), never as the app role;
- its only grants are `SELECT, UPDATE` on `outbox_events`; every other table is permission-denied;
- a dedicated policy `dispatcher_publish ON outbox_events TO knowledgeos_dispatcher USING (true)` makes all outbox rows visible to it (migration 0006);
- events carry only IDs and safe metadata (no document content), and workers re-enter the tenant context (`tenant_session(org)`) before touching tenant data.

`tests/test_ingestion_runner.py::test_dispatcher_role_can_only_touch_the_outbox` guards this.
