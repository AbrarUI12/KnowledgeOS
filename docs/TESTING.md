# Testing Strategy

## Goal

Tests verify **behaviour**, not implementation details. For KnowledgeOS the most important behaviour is security: tenant isolation, authorization before retrieval, and safe handling of untrusted files and text. Those properties get adversarial tests, not just happy paths.

## Test layers

| Layer | Where | Runs | What it covers |
|---|---|---|---|
| Backend unit | `apps/api/tests/test_*.py`, marker `unit` | `make test-unit` (no Docker) | pure functions, schemas, permission mapping, parsers, chunker, fusion, validators, error envelope |
| Backend integration | marker `integration` | `make test-int` (Docker required) | real PostgreSQL (with the Compose init scripts and roles), Redis, MinIO via **Testcontainers**: migrations, RLS, constraints, triggers, API endpoints with lifespan |
| Security | marker `security` (from Session 56 consolidated in `tests/security/`) | in `make test` | cross-tenant leakage, IDOR, restricted-title probing, malicious files, injection, citation tampering |
| Slow / model | markers `slow`, `llm` | nightly or manual | real embedding/reranker models, real LLM calls (Ollama/Groq) |
| Frontend unit/component | `apps/web/**/*.test.ts(x)` | `pnpm web:test` | reducers, hooks, components (Testing Library), **axe-core** accessibility, **token contrast** (`tests/contrast.test.ts`) |
| End-to-end | `apps/web/tests/e2e/` (Playwright, from task T1.7) | `pnpm --filter @knowledgeos/web exec playwright test` | critical journeys against the running stack (login, isolation, upload, search, ask → citation → source) |

## Conventions

- **Testcontainers, not the shared stack.** Integration tests start their own containers (random ports), so three agents can run them at the same time. The `make up` stack is for manual and E2E testing only.
- Integration fixtures live in `apps/api/tests/conftest.py`; helpers in `apps/api/tests/support.py` (`make_settings` never reads a developer's `.env`).
- Connect as **`knowledgeos_app`** (the runtime role) when testing isolation. Testing as the owner would bypass RLS and prove nothing.
- Each test cleans up the data it creates (see the `owner` fixture in `test_identity_schema.py`, which purges audit rows with the explicit purge flag).
- Hypothesis for invariants (authorization predicates, chunker properties, permission mappings).
- Malicious fixtures (EICAR, zip bombs, renamed executables) are **generated at test runtime, never committed**: Windows Defender deletes them on disk.
- Frontend: query by role and accessible name; don't assert exact animation frames, assert end states, focus and reduced-motion behaviour.
- Contract-dependent work uses fakes (`FakeLLM`, `FakeEmbeddingProvider`, `InMemoryObjectStore`) so it can be tested before the real provider exists.

## Commands

```bash
make lint typecheck test        # everything (Docker must be running)
make test-unit                  # backend unit only
make test-int                   # backend integration only
pnpm web:test                   # frontend unit/component
pnpm web:typecheck && pnpm web:lint
```

CI (`.github/workflows/ci.yml`) runs backend (Ruff, mypy, pytest unit + integration), frontend (ESLint + raw-color check, Prettier, tsc, Vitest, build), gitleaks and Docker builds on every PR. All four are required on `main`.

## Bug fix policy

Every reproducible bug gets a **regression test** that fails before the fix and passes after, when practical.

## Rules for AI agents

Agents must **never**:
- delete a failing test, or mark it skip/xfail, to make CI pass;
- weaken an assertion without a written justification in the PR;
- mock the exact behaviour the test is meant to verify;
- change expected values to match a broken implementation;
- test isolation as a superuser or owner role.

Exception: Claude may add **acceptance tests ahead of an implementation** marked `xfail(strict=True, reason="T<id> not implemented yet")`. The implementing task must remove the marker; strict xfail fails CI if the test unexpectedly passes.
