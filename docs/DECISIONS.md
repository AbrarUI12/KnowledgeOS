# Decisions

> The single place for **why** KnowledgeOS is built the way it is. Read the relevant entries before proposing a change that touches them. If you disagree with a decision, explain why it's no longer appropriate, using its "Revisit when" condition, and get the user's approval before acting.

Three kinds of records live here:

1. **ADRs**: significant architecture decisions, one file each in [`docs/adr/`](adr/README.md).
2. **D-NNN**: smaller decisions (tooling, conventions, environment).
3. **DV-NNN**: intentional deviations from the target spec in `plan.md`.

**Adding a decision:** append a row with the next free ID, today's date and the agent or person who made it. Never renumber or delete rows; mark superseded ones as `Superseded by …`. A significant architectural decision gets a full ADR file (copy [`docs/adr/TEMPLATE.md`](adr/TEMPLATE.md)) plus a row here.

---

## 1. Architecture Decision Records

| ADR | Title | Status | Summary |
|---|---|---|---|
| [ADR-001](adr/ADR-001-modular-monolith.md) | Modular monolith | Accepted | One FastAPI + Celery codebase with package boundaries; no microservices |
| [ADR-002](adr/ADR-002-postgres-pgvector-first-search.md) | PostgreSQL + pgvector first search | Accepted | Dense + full-text + trigram in Postgres; authorization in the same SQL; `SearchBackend` interface for later swaps |
| [ADR-003](adr/ADR-003-oidc-identity-app-authorization.md) | OIDC identity, app-owned authorization | Accepted | IdP authenticates; KnowledgeOS owns roles, groups, ACLs. Keycloak locally, Auth0 deployed |
| [ADR-004](adr/ADR-004-tenant-rls-strategy.md) | Tenant isolation with RLS | Accepted | `organization_id` on every tenant table + forced RLS + transaction-local context; runtime role can't bypass RLS; fail closed; cross-org → 404 |
| [ADR-005](adr/ADR-005-async-ingestion-transactional-outbox.md) | Async ingestion with a transactional outbox | Accepted | Outbox rows in the business transaction; dispatcher → Celery; idempotent checkpointed stages; Postgres is the source of truth |
| [ADR-006](adr/ADR-006-provider-abstraction.md) | Provider abstraction | Accepted | Every external capability behind an interface; policy-enforcing router; model IDs in config; no silent embedding substitution |
| [ADR-007](adr/ADR-007-index-generations.md) | Versioned index generations | Accepted | Candidate generations built side by side, evaluated, switched atomically, rollback retained |
| [ADR-008](adr/ADR-008-free-tier-deployment-topology.md) | Free-tier deployment topology | Accepted | Vercel + one HF Docker Space (supervisord) + Neon + B2 + Auth0; same image splits into services on paid infra |

## 2. Smaller decisions

| ID | Date | By | Decision | Reason | Revisit when |
|---|---|---|---|---|---|
| D-001 | 2026-10-11 | user | Whole project uses free tiers and open models only | No budget | A budget becomes available |
| D-002 | 2026-10-11 | Claude | Backend deploys to a **Hugging Face Docker Space** instead of Render/Railway | Render free has no background workers and 512 MB RAM (too small for Docling/OCR/models); Railway has no lasting free tier. HF CPU Basic gives 2 vCPU / 16 GB at $0 | HF free terms change, or a paid host is affordable |
| D-003 | 2026-10-11 | Claude | **Backblaze B2** is the default object store, Cloudflare R2 the alternative | R2 asks for a payment method on file; B2's 10 GB free tier does not. Both are S3-compatible | A payment method is available (R2 has free egress) |
| D-004 | 2026-10-11 | Claude | Embeddings and reranker run **in-process with open models** (Qwen3-Embedding-0.6B 1024-d; bge-reranker-v2-m3) | $0, no rate limits, data never leaves the deployment (satisfies local-only policy) | Quality or latency benchmarks show a hosted model is needed |
| D-005 | 2026-10-11 | Claude | Generation goes through one **OpenAI-compatible adapter** (Ollama locally; Groq free primary; Gemini free fallback) | One adapter covers many free providers; model IDs stay in config | A required provider isn't OpenAI-compatible |
| D-006 | 2026-10-11 | Claude | Hosted identity uses **Auth0 Free**; Keycloak stays for local development | Hosting Keycloak needs a paid always-on instance; the app is IdP-agnostic by design | Auth0 free terms change |
| D-007 | 2026-10-11 | user | Dev machine: 16 GB RAM + RTX 4060 Laptop (8 GB VRAM). Local dev uses **Ollama on the GPU** for generation (7–8B models at Q4, e.g. `qwen3:8b`) and can run embeddings/reranker on CUDA locally; deployed stays CPU | 8 GB VRAM fits a Q4 8B model. 16 GB RAM means the Compose `full` profile + Ollama is tight, so use `core` when running local models | Hardware changes |
| D-008 | 2026-10-12 | Claude | Local MinIO uses **`pgsty/minio`** (pinned `RELEASE.2026-08-04T00-00-00Z`) and `pgsty/mc` | The official `minio/minio` and `minio/mc` images no longer exist on Docker Hub; pgsty is the maintained community build. Local dev only | pgsty stops maintaining it (alternatives: SeaweedFS, Garage) |
| D-009 | 2026-10-12 | Claude | KnowledgeOS host ports: **Postgres 5433, Redis 6380** | 5432/6379 are used by another local project (`retailops-bd`). Configurable via `POSTGRES_PORT`/`REDIS_PORT` | – |
| D-010 | 2026-10-12 | Claude | Plan §27.3 colors adjusted for WCAG AA (light ink-tertiary #676B65, light warning #965C16, dark ink-tertiary #878D84) + new `control-border` token | The plan's values failed AA. Enforced by `apps/web/tests/contrast.test.ts` | Brand refresh |
| D-011 | 2026-10-12 | Claude | UI primitives = shadcn (radix base) generated into `components/primitives/` and restyled onto KnowledgeOS tokens (no `dark:` overrides, no `outline-none`, scrim without blur). Single-choice controls use `SegmentedControl` (radio group), not Tabs | Accessible Radix behaviour + distinct visual identity | – |
| D-012 | 2026-10-12 | Claude | Schema conventions: text + CHECK instead of PG enums; composite FKs `(x_id, organization_id)` for tenant integrity; grants in migrations (guarded, validated identifiers); system roles seeded with deterministic UUIDv5 IDs as a literal snapshot | Enums are hard to evolve; composite FKs make cross-tenant references impossible; migrations behave the same everywhere | – |
| D-013 | 2026-10-12 | user + Claude | **Three-agent workflow:** Claude (architect, reviewer, security/DB/integration track), Codex (libraries, frontend foundation, Ask experience, reviews Claude's PRs), Cline (UI pages, scripts, local QA). Tasks in `docs/TASKS.md`; cross-agent review before auto-merge; worktrees per agent; only Claude writes migrations. See `docs/AGENT_WORKFLOW.md` | Parallel delivery up to M1 without conflicting edits or duplicated work | The team or tooling changes, or after M1 |
| D-014 | 2026-10-12 | Claude | RLS is **forced on every tenant table, binding the owner role too**. Context is transaction-local (`app.organization_id`, `app.user_id`) read through `kos_current_org_id()` / `kos_current_user_id()` (NULLIF guards the `''` a pooled connection returns after a local set). Test setup/cleanup uses the container superuser; isolation is verified as `knowledgeos_app`. Migrations that write tenant rows must set the context (or temporarily `NO FORCE` inside the migration); readiness fails if the runtime role is superuser, BYPASSRLS or owns tables | Defence in depth: even a misconfigured runtime connecting as owner sees nothing without context (ADR-004) | A table needs cross-tenant reads (use a narrow SECURITY DEFINER function, reviewed) |
| D-015 | 2026-10-23 | user + Claude | **M1 fast track:** finish M1 (live staging) in 3–5 days with **Claude and Codex only**; Cline paused and its open tasks reassigned or cut (`docs/TASKS.md` §0). Lighter loop: one PR per lane item, same-session reviews, only BLOCKER/HIGH block a merge (MEDIUM/LOW become a follow-up issue unless security), full suite in CI only, one final gate verification instead of G1–G4 tags | Every gate was waiting on the unstarted UI backlog; the backend was nearly complete | After M1, when Sessions 34–65 are planned |

## 3. Deviations from plan.md

`plan.md` is the target architecture. Every intentional difference is recorded here.

| ID | plan.md ref | Deviation | Reason | Reversible? |
|---|---|---|---|---|
| DV-001 | §4.1, §38.2 | Demo deployment runs api/worker/dispatcher/scheduler in **one container** (supervisord) | Free hosting allows one container; same image, so it splits back out on paid infrastructure | Yes |
| DV-002 | §38.2 | Render/Railway replaced by Hugging Face Spaces | See D-002 | Yes |
| DV-003 | §5.4 | No paid cloud embedding/reranker. Local open models are the default for all KBs | See D-004 | Yes (add provider) |
| DV-004 | §35 | Real spend is $0. The cost ledger records tokens plus **list-price estimates** from a versioned pricing table | Keeps cost analytics meaningful on free tiers | n/a |
| DV-005 | §36.1 | The 100k+ chunk benchmark runs locally, not on hosted Neon (1 GB free storage) | Free-tier storage | Yes |
| DV-006 | §38.2 | Redis in the deployed demo runs inside the backend container (ephemeral) | Upstash free quotas can't absorb Celery polling; Redis is non-authoritative (§34.5) | Yes |
| DV-007 | §27.3 | Some reference color tokens changed and `control-border` added | WCAG AA (plan requires validating contrast); see D-010 | Yes |
| DV-008 | §27, §28, S11, S29, S31, S33 | Cut for M1: Playwright E2E suite (→ `scripts/smoke.py` + manual walk-through), answer conflict detection, copy-answer formatters, rich answer-state cards, keep-warm workflow, deploy-on-push workflow (manual deploy), separate G1–G4 gate tags, per-gate QA passes. Admin pages, ingestion Inspect and the retrieval debugger ship lean | 3–5 day M1 deadline (D-015); none of these protect tenant isolation, authorization or grounding | Yes (post-M1 backlog) |
| DV-009 | §21, S29 | The SSE stream sends the answer **after** validation (citations, one bounded correction, link/image/HTML stripping) as `answer_delta` paragraphs, not token by token; a `: keep-alive` comment every 15 s covers slow models. Event shapes are unchanged (`docs/api/sse-events.md`) | A streamed answer whose citations later fail can't be un-shown; fail-safe grounding over time-to-first-token for M1 | Yes (stream tokens and flag invalid citations in place) |
