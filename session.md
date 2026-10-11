# session.md — KnowledgeOS Session-by-Session Build Plan

> **What this is:** the complete execution plan that turns `plan.md` (the architecture spec) into working software, from an empty folder to a production deployment and a v1.0.0 release.
>
> **How big:** **65 sessions** grouped into **17 sprints**, plus Session 00 (planning, done).
> **Budget:** **$0**. Every service is a free tier or open-source model (see *Locked decisions*).
> **Progress lives in:** `agent.md`. This file says *what to do*; `agent.md` says *what has been done*.

---

## Table of contents

1. [How to use this file](#1-how-to-use-this-file)
2. [Session rules](#2-session-rules)
3. [Locked decisions ($0 stack)](#3-locked-decisions-0-stack)
4. [Accounts checklist](#4-accounts-checklist)
5. [Roadmap overview](#5-roadmap-overview)
6. [Gates & milestones](#6-gates--milestones)
7. [Sessions](#7-sessions)
   - Sprint 0 · Foundation (01–05)
   - Sprint 1 · Identity & tenancy (06–11)
   - Sprint 2 · Knowledge bases & secure upload (12–15)
   - Sprint 3 · Reliable ingestion (16–21)
   - Sprint 4 · Indexing & retrieval (22–26)
   - Sprint 5 · Grounded answers (27–31)
   - Sprint 6 · MVP deployment (32–33)
   - Sprint 7 · Conversations & routing (34–37)
   - Sprint 8 · Evaluation platform (38–42)
   - Sprint 9 · Observability & cost (43–46)
   - Sprint 10 · Document lifecycle (47–49)
   - Sprint 11 · Connectors (50–52)
   - Sprint 12 · Model policy (53–54)
   - Sprint 13 · Security hardening (55–57)
   - Sprint 14 · Performance & resilience (58–59)
   - Sprint 15 · Production (60–62)
   - Sprint 16 · Polish & release (63–65)
8. [Appendix A: Definition-of-Done traceability (plan §44)](#appendix-a--definition-of-done-traceability-plan-44)
9. [Appendix B: Demo scenarios (plan §41)](#appendix-b--demo-scenarios-plan-41)
10. [Appendix C: plan.md phase → session map](#appendix-c--planmd-phase--session-map)
11. [Appendix D: Mandatory security cases (plan §39.4)](#appendix-d--mandatory-security-cases-plan-394)
12. [Appendix E: Risks to this session plan](#appendix-e--risks-to-this-session-plan)

---

## 1. How to use this file

- **A session is one sprint-sized chunk of work** with one goal, a task list, tests and a *Done when* check. It is sized to finish in one sitting / one AI-coding conversation. Some sessions take an afternoon, others a weekend. Either is fine. **Do not start the next session until *Done when* is true.**
- **Sessions are sequential.** Each one builds on the previous ones. If two people work together, a frontend session can usually run one step behind its backend session in the same sprint.
- **Gates (G0–G15) are hard stops.** They are the exit gates from `plan.md` §40. If a gate fails, fix it before moving on. That is the plan's main defence against expensive rewrites.
- **Read order every time:** `agent.md` (status) → this file's current session → only the `plan.md` sections that session references (`§` numbers).
- **If a session is too big**, split it into `NNa` / `NNb`, add the rows to `agent.md`'s tracker, and don't renumber later sessions.
- **If reality disagrees with this file** (a library changed, a free tier changed), adapt, then record the deviation in `agent.md` §10.

---

## 2. Session rules

### 2.1 Start ritual (≈10 minutes)

1. Read `agent.md` §1 (status) and the newest session-log entry (§7).
2. `git pull` and `git status`. The working tree must be clean.
3. From Session 03 on: `make up` then `make test` to confirm a green baseline **before** changing anything.
4. Read this session's section and the referenced `plan.md` sections.
5. Create a branch: `git switch -c session/NN-short-name`.

### 2.2 During the session

- Work through the tasks in order. Write tests **with** the code, not afterwards.
- Stay in scope. If you notice future work, log it in `agent.md` §8 as type `Later`. Don't build it now.
- You may tick checkboxes in this file as you go, but **`agent.md` is the authoritative status**.
- Never commit secrets. Use `.env` (git-ignored) and keep `.env.example` updated with variable **names**.

### 2.3 End ritual

1. Run everything green: `make lint typecheck test` (and the frontend equivalents once they exist).
2. Check every *Done when* item yourself (run the commands, click through the UI).
3. Update `agent.md` following its §2 update protocol.
4. Commit using the suggested message (Conventional Commits), push, open a PR, wait for CI to pass, merge.
5. If the session closes a gate: `git tag gate-GN` and `git push --tags`.

### 2.4 Definition of done (applies to every session)

- [ ] Code formatted, linted and type-checked (Ruff + mypy, ESLint + `tsc --noEmit`).
- [ ] New behaviour is covered by tests, and all tests pass locally and in CI.
- [ ] No secrets in git (gitleaks clean).
- [ ] Migrations: `upgrade` works from the previous head, and `downgrade` works where reversible.
- [ ] Every new **tenant-scoped table** has `organization_id`, RLS enabled + forced, a policy, and is covered by the "all tenant tables have RLS" meta-test (from Session 12).
- [ ] API changes are visible in OpenAPI, and the frontend client is regenerated (from Session 10).
- [ ] New env vars are added to `.env.example` and to `agent.md` §11.
- [ ] Docs (README / runbook / ADR) are updated when behaviour or setup changed.
- [ ] `agent.md` is updated.

### 2.5 Conventions

| Topic | Convention |
|---|---|
| Branches | `session/NN-slug` → PR → `main` |
| Commits | Conventional Commits: `feat(api): …`, `fix(rag): …`, `test(security): …`, `docs: …`, `chore: …`, `ci: …`, `perf: …` |
| Python | Ruff (format + lint), mypy strict on `app/`, pytest markers `unit`, `integration`, `security`, `slow`, `llm` |
| TypeScript | `strict: true`, ESLint, Prettier, Vitest, Playwright |
| Task runner | Root `Makefile` (`make up`, `make test`, …). On Windows install GNU make (`winget install ezwinports.make`) and run it from PowerShell or Git Bash |
| IDs | UUID primary keys everywhere. Never use slugs for authorization |
| Time | `timestamptz`, always UTC |
| API | `/v1/...`, JSON error envelope, cursor pagination, `Idempotency-Key` on important creates |
| Line endings | LF (enforced by `.gitattributes`). This matters on Windows for shell scripts used in Docker |

### 2.6 Kickoff prompt template (for Claude Code or any AI coding agent)

```text
We are building KnowledgeOS. First read agent.md (status block + newest session-log entry),
then the section "Session NN — <title>" in session.md, then only the plan.md sections it references.
Implement Session NN completely: every task, the tests, and every "Done when" check.
Do not start Session NN+1. Follow the definition of done in session.md §2.4.
When finished: run lint, typecheck and tests, update agent.md following its update protocol,
and propose the commit message given in the session.
```

---

## 3. Locked decisions ($0 stack)

### 3.1 Why things differ from plan.md §38.2

The project has **no budget**. Free tiers were checked on 2026-10-11:

- **Render's free tier has no background workers**, and its 512 MB web instances spin down after 15 minutes. That can't run Celery + Docling + OCR + ClamAV. Railway has no lasting free tier.
- **Hugging Face Docker Spaces (CPU Basic)** are free with 2 vCPU / 16 GB RAM / 50 GB ephemeral disk, and sleep after 48 h without traffic. That's enough for API + workers + document parsing + local embedding/reranker models in **one container**.
- **Cloudflare R2** asks for a payment method on file, so **Backblaze B2** (10 GB free, no card) is the default. Both speak the S3 API, so switching is a config change.
- **Neon Free** gives 1 GB storage per project, 10 branches and pgvector. Compute scales to zero after 5 minutes idle.

### 3.2 The stack

| Concern | Local development | Deployed (free) |
|---|---|---|
| Frontend | Next.js (App Router) + TypeScript on host | **Vercel Hobby** |
| API | FastAPI in Docker or on host (`uv run`) | **Hugging Face Docker Space**: one container runs api + Celery workers + dispatcher + beat + Redis + clamd under **supervisord** (ADR-008). Staging = a second Space |
| Workers | Celery in Docker (Linux only) | same container as the API |
| PostgreSQL + pgvector | `pgvector/pgvector:pg17` | **Neon Free** (prod = `main` branch, staging = `staging` branch) |
| Redis | `redis:7-alpine` | in-container Redis (ephemeral; PostgreSQL is the durable source of truth, plan §34.5) |
| Object storage | MinIO | **Backblaze B2** (S3 API). Cloudflare R2 if a card is available |
| Identity (OIDC) | Keycloak | **Auth0 Free** (Zitadel Cloud free is an alternative). The app is IdP-agnostic (plan §5.6) |
| Document parsing | Docling (+ Tesseract/RapidOCR) | same |
| Embeddings | **Qwen3-Embedding-0.6B**, 1024-d, in-process (sentence-transformers). **bge-m3** (1024-d) is the evaluated alternative | same, in-process. $0, no rate limits, counts as "local" |
| Reranker | **bge-reranker-v2-m3** cross-encoder (ONNX, CPU). Qwen3-Reranker-0.6B (seq-cls variant) as an alternative | same |
| Generation LLM | **Ollama** through the OpenAI-compatible adapter (small models such as `qwen3:4b`, `llama3.2:3b`). Use Groq instead if the laptop is too slow | **Groq free tier** primary → **Gemini free tier** fallback → OpenRouter `:free` models optional. All go through **one OpenAI-compatible adapter**. Model IDs live in config only |
| Malware scanning | ClamAV container (`full` profile) | ClamAV inside the Space image |
| Traces / metrics / logs | `grafana/otel-lgtm` container (`obs` profile) | **Grafana Cloud Free** (OTLP) + **Langfuse Cloud Hobby** |
| CI/CD | GitHub Actions | GitHub Actions + **GHCR**. Keep the repo **public** for unlimited Actions minutes |
| Invitations email | Mailpit | copyable invite links (Resend free tier optional) |
| IaC | – | Terraform (Vercel, Neon, B2/R2, Auth0, Grafana) + `huggingface_hub` script for Spaces + an **AWS reference module** that is validated but never applied |

### 3.3 Rules that follow from the free stack

1. **Data rule:** free cloud LLM tiers may retain or train on prompts. Use **only synthetic/demo documents** with cloud generation. The model policy caps external providers at `public`/`internal` classification by default.
2. **Rate limits are a design input.** The LLM gateway throttles per provider, honours `Retry-After`, and falls back only to policy-allowed models (Session 28).
3. **Cost analytics still matter.** Real spend is $0, but the ledger records tokens plus **list-price estimates** from a versioned pricing table (Session 45).
4. **Neon's 1 GB storage** means the 100k+ chunk benchmark runs **locally** (Session 58). `halfvec(1024)` is evaluated as a storage saver.
5. **CPU reranking** may miss the plan's 500 ms retrieval P95. Measure, tune, and revise the target with evidence if needed (plan §2.2 allows this).
6. **Windows 11 Home:** install Docker Desktop with the WSL2 backend. Celery, Docling, OCR and ClamAV run **only in Linux containers**. Docker Compose profiles (`core`, `full`, `obs`, `local-models`) keep laptop RAM under control.
7. **Free tiers change.** Re-verify limits in Session 32 and Session 60, and record them in `docs/runbooks/free-tier-limits.md`.

### 3.4 Versions policy

- Python **3.12**, Node.js **current LTS**, PostgreSQL **17** (matches Neon) with pgvector **≥ 0.8** (needed for iterative HNSW scans), Redis **7**.
- Latest stable at Session 01 for: FastAPI, Pydantic 2, SQLAlchemy 2 (async), Alembic, Celery 5, Next.js (App Router), React, Tailwind CSS, Motion for React (`motion/react`), TanStack Query/Table/Virtual, Zod, Auth.js, Docling, sentence-transformers.
- **Pin exact versions** in `uv.lock` and `pnpm-lock.yaml`. Upgrade deliberately (Renovate/Dependabot PRs), never silently.
- Pin Docling and parser versions: their output changes between releases and would churn snapshot tests and index generations.

### 3.5 Non-goals (plan §2.3, still in force)

No autonomous agents, no tool calling from retrieved content, no fine-tuning, no SQL agent, no payments, no certification claims, no hyperscale architecture, no video/audio reasoning.

---

## 4. Accounts checklist

All free. **None need a credit card** except the optional Cloudflare R2 alternative.

| Account | First needed | Used for | Notes |
|---|---|---|---|
| GitHub | S01 | Code, Actions, GHCR | Public repo = unlimited Actions minutes |
| Docker Desktop | S02 | Local stack | Free for personal use; enable the WSL2 backend |
| Hugging Face | S22 (optional token), S32 | Model downloads, backend hosting (Spaces) | Public models need no token; the Space must be public (the app enforces auth) |
| Groq | S28 | Free cloud generation | Check per-model RPM/TPM/RPD in the Groq console |
| Google AI Studio (Gemini API) | S28 | Fallback generation, eval judge | Free-tier limits are per project; check the official page |
| Neon | S32 | Managed Postgres + pgvector | Free: 1 GB/project, 10 branches |
| Backblaze B2 | S32 | Object storage | 10 GB free. Enable S3-API CORS |
| Auth0 | S32 | Hosted OIDC | Free plan |
| Vercel | S32 | Frontend hosting | Hobby plan (non-commercial) |
| Langfuse Cloud | S43 | RAG traces | Hobby plan |
| Grafana Cloud | S44 | Metrics, traces, logs, alerts | Free forever tier |
| Google Cloud project | S51 | Google Drive API OAuth | Drive API needs no billing; OAuth consent screen in "testing" mode |
| HCP Terraform | S60 | Terraform remote state | Free tier |
| Cloudflare (optional) | S32 | R2 instead of B2 | Requires a payment method on file |
| Resend (optional) | S09/S62 | Invitation emails | Free tier; otherwise use copyable links |

---

## 5. Roadmap overview

| Sprint | Sessions | Theme | plan.md phase | Frontend phase | Ends with |
|---|---|---|---|---|---|
| 0 | 01–05 | Foundation | Phase 0 | FE-0 | **G0** |
| 1 | 06–11 | Identity, tenancy, authorization | Phase 1 | FE-1 | **G1** |
| 2 | 12–15 | Knowledge bases & secure upload | Phase 2 | FE-2 (part 1) | **G2** |
| 3 | 16–21 | Reliable ingestion | Phase 3 | FE-2 (part 2) | **G3** |
| 4 | 22–26 | Indexing & retrieval-only search | Phase 4 | FE-3, FE-7 (debugger v1) | **G4** |
| 5 | 27–31 | Reranking, grounded generation, citations | Phase 5 | FE-4 | **G5** (MVP core) |
| 6 | 32–33 | Early MVP staging deployment | Phase 14 (subset) | – | **M1** (live demo) |
| 7 | 34–37 | Conversations, routing, projects, compare | Phase 6 | FE-5 | **G6** |
| 8 | 38–42 | Evaluation platform | Phase 7 | FE-7 (eval lab) | **G7** |
| 9 | 43–46 | Observability, feedback, cost | Phase 8 | FE-8 | **G8** |
| 10 | 47–49 | Document lifecycle & zero-downtime reindex | Phase 9 | – | **G9** |
| 11 | 50–52 | Connectors & permission sync | Phase 10 | FE-6 (part 1) | **G10** |
| 12 | 53–54 | Local/cloud model policy | Phase 11 | FE-6 (part 2) | **G11** |
| 13 | 55–57 | Security hardening | Phase 12 | FE-6 (part 3) | **G12** |
| 14 | 58–59 | Performance & resilience | Phase 13 | – | **G13** |
| 15 | 60–62 | Production CI/CD & deployment | Phase 14 | – | **G14** (production live) |
| 16 | 63–65 | Polish & release evidence | Phase 15 | FE-9, FE-10 | **G15** / v1.0.0 |

---

## 6. Gates & milestones

A gate passes only when **every** criterion is demonstrably true. Record evidence in `agent.md` §6.

| Gate | After | Exit criteria |
|---|---|---|
| **G0** | S05 | API, web, Postgres, Redis and object storage run locally · CI green · first migration reproducible (up/down/up) · no stock shadcn styling visible · focus states and reduced motion work |
| **G1** | S11 | Two test organizations cannot read each other's data through the API **or** direct repository calls · role permissions enforced · shell keyboard navigation and responsive panes work · Playwright login journey green |
| **G2** | S15 | A valid file produces a durable document version + queued ingestion job · malicious/unsupported fixtures fail safely with stable error codes |
| **G3** | S21 | All core formats (plan §5.3) parse into canonical artifacts · killing a worker mid-job does not duplicate chunks · failed jobs are diagnosable and retryable **from the UI** without reading logs |
| **G4** | S26 | Exact identifiers (e.g. `HR-142-B`) and semantic paraphrases both retrieve well · restricted chunks are never returned · only the active index generation is searched |
| **G5** | S31 | Every successful business answer has valid source aliases · the no-answer fixture abstains · the poisoned fixture cannot override system policy · citation → source works for PDF and at least one non-PDF type |
| **M1** | S33 | Public staging URL: sign in → upload → READY → search → ask with citations, all working on the $0 stack |
| **G6** | S37 | Follow-up questions stay grounded · a permission change between turns is respected · cross-document work (projects, compare) no longer depends only on chat history |
| **G7** | S42 | Every RAG profile change produces reproducible metrics · security-gate failures block promotion |
| **G8** | S46 | A bad answer can be traced from the user's query through selected evidence to the model response · token/cost (list-price estimate) is visible · charts link to inspectable data |
| **G9** | S49 | A replaced/retired document is no longer retrieved · deleted chunks cannot be found · index-generation rollback works |
| **G10** | S52 | Changed, deleted and re-permissioned source data propagates correctly · the UI shows backend-confirmed propagation |
| **G11** | S54 | A local-only KB makes **zero** external model-provider requests, proven by an automated test |
| **G12** | S57 | Mandatory security regression suite passes · no unresolved critical/high finding · security-sensitive UI state is explicit and backend-confirmed |
| **G13** | S59 | Benchmark results and bottleneck analysis documented · SLOs met or explicitly revised with evidence |
| **G14** | S62 | A fresh environment can be provisioned and deployed from the repository · restore and rollback procedures documented **and tested** · production live |
| **G15** | S65 | An outside reviewer can understand and run the product without private explanation · every plan §44 item checked with evidence · v1.0.0 released |

---

## 7. Sessions

Each session uses the same template: **Refs** (plan.md sections) · **Depends on** · **Goal** · **Tasks** · **Files** · **Tests** · **Done when** · **Pitfalls** · **Close-out**.

---

## Sprint 0 — Foundation (plan Phase 0, FE-0) → G0

### Session 01 — Repository bootstrap & tooling

**Refs:** §3, §5.1, §5.5, §5.8, §6, §40 Phase 0 · **Depends on:** Session 00

**Goal:** a clean monorepo with backend and frontend skeletons, quality tooling, and agent onboarding files, so every later session starts from the same structure.

**Tasks**
- [ ] Install prerequisites: Git, Docker Desktop (WSL2 backend), `uv` (then `uv python install 3.12`), Node.js LTS, `pnpm` (`corepack enable`), GNU make, optionally GitHub CLI.
- [ ] `git init -b main`. Run `git config core.longpaths true` (Windows).
- [ ] Add `.gitignore` (Python, Node, `.env*` except `.env.example`, `.venv`, `node_modules`, `.next`, coverage, Terraform state, `evals/experiments/*/raw`), `.gitattributes` (`* text=auto eol=lf`), `.editorconfig`.
- [ ] Create the plan §6 directory skeleton with `.gitkeep` files: `apps/api`, `apps/web`, `packages/contracts`, `evals/{datasets,rubrics,experiments,scripts}`, `tests/{integration,security,load,e2e}`, `infra/{docker,compose,terraform,monitoring}`, `configs/{prompts,rag_profiles,policies}`, `docs/{adr,architecture,threat-model,api,runbooks,evaluation}`, `scripts`, `.github/workflows`.
- [ ] Backend: `uv init --app` inside `apps/api` with package `app/` laid out per plan §6 (`api/`, `auth/`, `core/`, `db/`, `domain/`, `ingestion/`, `rag/...`, `providers/...`, `security/`, `services/`, `observability/`, `workers/`).
  - Runtime deps: `fastapi`, `uvicorn[standard]`, `pydantic`, `pydantic-settings`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `structlog`, `httpx`, `tenacity`.
  - Dev deps: `ruff`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-cov`, `hypothesis`, `testcontainers[postgres,redis,minio]`, `respx`, `syrupy`.
  - Configure Ruff (line length 100, sensible rule set), mypy (strict for `app/`), pytest (`asyncio_mode = "auto"`, markers).
- [ ] Minimal `app/main.py` exposing `GET /health/live`.
- [ ] Frontend: `pnpm create next-app apps/web` (TypeScript, ESLint, Tailwind, App Router, `@/*` alias). Set TS `strict`. Create the plan §27.27 folders (`components/{primitives,shell,motion,command,tables,feedback}`, `features/*`, `lib/*`, `styles/`). Add Vitest + Testing Library + one trivial test. Add Prettier.
- [ ] Root `pnpm-workspace.yaml` (`apps/web`, `packages/*`).
- [ ] Root `Makefile`: `install`, `lint`, `format`, `typecheck`, `test`, `api`, `web`.
- [ ] `pre-commit` config: ruff, ruff-format, gitleaks, end-of-file-fixer, trailing-whitespace, check-yaml, check-added-large-files. Run `pre-commit install`.
- [ ] `README.md` skeleton: what KnowledgeOS is, status, links to `plan.md`, `session.md`, `agent.md`.
- [ ] `CLAUDE.md`: a 1-paragraph project summary, the **read order** (`agent.md` → `session.md` current session → referenced `plan.md` §), the conventions from §2.5, the key `make` commands, and "update `agent.md` before stopping". Add `AGENTS.md` with the same content (a copy, since symlinks on Windows need Developer Mode) so other coding agents find it too.
- [ ] Create the GitHub repo (public recommended) and push.

**Files:** `.gitignore`, `.gitattributes`, `.editorconfig`, `Makefile`, `.pre-commit-config.yaml`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `pnpm-workspace.yaml`, `apps/api/pyproject.toml`, `apps/api/app/main.py`, `apps/web/*`

**Tests:** `apps/api/tests/test_health.py` (httpx `AsyncClient` + `ASGITransport` → `/health/live` 200) · one Vitest smoke test.

**Done when**
- A fresh clone runs `make install && make lint && make test` successfully.
- `make api` serves `http://localhost:8000/health/live`, and `make web` renders the Next.js page.
- `pre-commit run --all-files` is clean, and gitleaks reports no findings.

**Pitfalls:** CRLF line endings break shell scripts in containers (hence `.gitattributes`). Long Windows paths in `node_modules` (hence `core.longpaths`). Use one shell (PowerShell or Git Bash) consistently for `uv`/`pnpm`.

**Close-out:** update `agent.md` §4.1–4.2 with the exact install commands. Commit `chore: bootstrap monorepo, tooling and agent onboarding files`.

---

### Session 02 — Local infrastructure (Docker Compose)

**Refs:** §4.1, §5.2, §5.6, §38.1 · **Depends on:** 01

**Goal:** one command brings up every local dependency, healthy and pre-configured.

**Tasks**
- [ ] Root `docker-compose.yml` (detail files under `infra/compose/` are fine) with **profiles**:
  - `core` (default): `postgres`, `redis`, `minio` + `minio-init`, `keycloak`, `mailpit`
  - `full`: adds `clamav` (and later `worker`, `dispatcher`, `beat`)
  - `obs` (S43) and `local-models` (S53) are added later
- [ ] **postgres:** `pgvector/pgvector:pg17`, `pg_isready` healthcheck, named volume. Init scripts in `infra/docker/postgres/init/`:
  - `01-extensions.sql`: `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;`
  - `02-roles.sql`: `knowledgeos_owner` (owns schema, used for migrations), `knowledgeos_app` (runtime: `LOGIN NOSUPERUSER NOBYPASSRLS`), `knowledgeos_dispatcher` (S16). Grants are handled by migrations.
  - `03-keycloak-db.sql`: a separate `keycloak` database.
- [ ] **redis:** `redis:7-alpine`, `redis-cli ping` healthcheck, no persistence needed.
- [ ] **minio:** server + console. The `minio-init` job (`minio/mc`) creates buckets `kos-quarantine`, `kos-trusted`, `kos-artifacts`, sets a 7-day expiry lifecycle on quarantine, and allows CORS from `http://localhost:3000` (MinIO server env `MINIO_API_CORS_ALLOW_ORIGIN`).
- [ ] **keycloak:** `quay.io/keycloak/keycloak` (current major) in `start-dev --import-realm` mode with `infra/docker/keycloak/realm-knowledgeos.json`:
  - client `knowledgeos-web` (confidential, standard flow + PKCE, redirect `http://localhost:3000/*`)
  - client/audience `knowledgeos-api` (audience mapper so access tokens carry `aud: knowledgeos-api`)
  - `email` and `profile` claims
  - dev users with dev-only passwords: `alice@acme.test` (Acme admin), `bob@acme.test` (Acme member), `hana@acme.test` (Acme HR manager), `carol@globex.test` (Globex admin)
  - direct-access grants enabled **in the dev realm only** (used by test scripts)
  - set `KC_HOSTNAME` so the token issuer is identical from browser and containers
- [ ] **mailpit:** SMTP 1025, UI 8025.
- [ ] **clamav** (`full` profile): `clamav/clamav:stable`, port 3310. It needs ~1.5 GB RAM and runs freshclam on start.
- [ ] `.env.example` with every variable (DB URLs for owner/app roles, Redis, S3 endpoint/keys/buckets, OIDC issuer/audience/JWKS, SMTP).
- [ ] Makefile: `up` (core), `up-full`, `down`, `reset` (down + delete volumes), `logs`, `ps`, `psql`, `infra-check`.
- [ ] `scripts/check_infra.py`: connect to Postgres and verify extensions + roles exist (`rolbypassrls = false` for the app role), Redis ping, MinIO list buckets, Keycloak discovery (`/.well-known/openid-configuration`), Mailpit HTTP, ClamAV `PING` (when the profile is up).

**Files:** `docker-compose.yml`, `infra/docker/postgres/init/*.sql`, `infra/docker/keycloak/realm-knowledgeos.json`, `.env.example`, `scripts/check_infra.py`

**Tests:** `make infra-check` passes on a fresh `make reset && make up`.

**Done when**
- `make up` gets all `core` services healthy in about 2 minutes, and `make up-full` adds ClamAV.
- `make infra-check` is all green.
- You can log in as `alice@acme.test` on the Keycloak account page for the realm.

**Pitfalls:** Docker Desktop memory (Settings → Resources, or `%UserProfile%\.wslconfig`); see `agent.md` I-002. Windows reserves some ports for Hyper-V (`netsh int ipv4 show excludedportrange protocol=tcp`), so map Postgres to 5433 if 5432 is taken. Keycloak imports the realm only on first start (`make reset` to re-import).

**Close-out:** fill `agent.md` §4.3, close or update I-002. Commit `chore(infra): local docker compose stack`.

---

### Session 03 — Backend core skeleton

**Refs:** §3, §5.1, §7.1, §26.1, §26.2 (Operations), §31 · **Depends on:** 02

**Goal:** a production-shaped FastAPI skeleton with config, logging, errors, database access, migrations, health checks and a real-database test harness.

**Tasks**
- [ ] `app/core/config.py`: `pydantic-settings` `Settings` with environment enum (`local`, `test`, `staging`, `production`), `SecretStr` for secrets, and a cached `get_settings()`.
- [ ] `app/core/logging.py`: structlog JSON output (console renderer locally), a redaction processor (`authorization`, `password`, `token`, `secret`, `api_key`, `cookie`), and `request_id` bound per request.
- [ ] Middleware: request ID (accept an incoming `X-Request-ID` only if it is a valid UUID, else generate; echo it in the response), timing, access log.
- [ ] `app/api/errors.py`: error envelope `{"error": {"code", "message", "request_id", "details"}}`. `AppError` hierarchy (`NotFound`, `Forbidden`, `Unauthorized`, `Conflict`, `ValidationFailed`, `RateLimited`, `ServiceUnavailable`). Handlers for `HTTPException`, `RequestValidationError` and unhandled exceptions (safe 500, no stack traces in the response).
- [ ] Router: `app/api/v1/router.py` mounted at `/v1`. Stable OpenAPI operation IDs (`generate_unique_id_function`) for client generation.
- [ ] Database: `app/db/session.py` async engine (asyncpg) + session factory + `get_db` dependency (one transaction per request) · `app/db/base.py` with MetaData naming conventions, UUID primary-key mixin (UUIDv7 via `uuid-utils` for index locality) and a timestamp mixin (`timestamptz`, `server_default=now()`).
- [ ] Alembic: async `env.py` using `DATABASE_MIGRATION_URL` (owner role). Migration `0001`: extensions (`vector`, `pg_trgm`) with `IF NOT EXISTS`.
- [ ] Health: `/health/live` (process up) · `/health/ready` (DB `SELECT 1`, Redis ping, object-store `head_bucket`, each with a short timeout, 503 if any fail, no secrets in output).
- [ ] Test harness `apps/api/tests/conftest.py`: session-scoped Testcontainers Postgres (`pgvector/pgvector:pg17`) with migrations applied, per-test isolation (transaction rollback or truncate), httpx `AsyncClient` fixture, Redis + MinIO containers for `integration`-marked tests.
- [ ] Makefile: `api` (uvicorn `--reload`), `migrate`, `migration name=...`, `test-unit`, `test-int`, `test`.

**Files:** `apps/api/app/core/*`, `apps/api/app/api/*`, `apps/api/app/db/*`, `apps/api/migrations/*`, `apps/api/alembic.ini`, `apps/api/tests/conftest.py`

**Tests:** settings parsing · error envelope shape for 404/422/500 · request-ID propagation · readiness 200 with the stack up and 503 with a bad DB URL · migration up → down → up.

**Done when**
- `make api`, then `/docs` shows the OpenAPI UI and `/health/ready` returns 200.
- `make migrate` on a fresh DB succeeds, and `make test` (unit + integration) is green.

**Pitfalls:** Testcontainers needs Docker Desktop running (if Ryuk fails on Windows, set `TESTCONTAINERS_RYUK_DISABLED=true` locally only). **Never use session-level `SET`.** Later sessions use only transaction-local `set_config(..., true)`.

**Close-out:** fill `agent.md` §4.4–4.5. Commit `feat(api): core config, logging, errors, database and health checks`.

---

### Session 04 — CI pipeline, Dockerfiles & ADRs

**Refs:** §5.8, §37.1, §38, §40 Phase 0 (ADRs) · **Depends on:** 03

**Goal:** every push is checked automatically, the backend builds into a container, and the key architecture decisions are written down.

**Tasks**
- [ ] `infra/docker/backend.Dockerfile`: multi-stage build (uv builder with `uv sync --frozen --no-dev` → `python:3.12-slim` runtime), non-root user, build targets `api` and `worker` sharing one image (ADR-008). Add `.dockerignore`.
- [ ] `infra/docker/web.Dockerfile`: Next.js `output: "standalone"` (for completeness; Vercel deploys the web app).
- [ ] `.github/workflows/ci.yml` (concurrency group with cancel-in-progress):
  - `backend`: setup uv + cache → `uv sync --frozen` → `ruff check` → `ruff format --check` → `mypy` → `pytest` (unit + integration; Testcontainers works on `ubuntu-latest`)
  - `migrations`: Postgres service container → `alembic upgrade head` → `downgrade base` → `upgrade head`
  - `frontend`: pnpm cache → `pnpm install --frozen-lockfile` → lint → typecheck → vitest → build
  - `secrets`: gitleaks action
  - `docker`: build the backend image (no push)
- [ ] Renovate or Dependabot config for uv, pnpm, GitHub Actions and Docker base images.
- [ ] Branch protection on `main`: CI required (free for public repos).
- [ ] ADRs in `docs/adr/` (template: Status, Context, Decision, Consequences, Alternatives):
  - ADR-001 Modular monolith · ADR-002 PostgreSQL/pgvector-first search · ADR-003 OIDC identity with app-owned authorization · ADR-004 Tenant RLS strategy · ADR-005 Async ingestion + transactional outbox · ADR-006 Provider abstraction · ADR-007 Index generations
  - **ADR-008 Free-tier deployment topology**: HF Space all-in-one container (supervisord), Vercel, Neon, B2, Auth0. Explain how it maps back to the separate plan §4.1 deployment units and how to split it on paid infrastructure.
- [ ] `docs/architecture/overview.md`: system diagram (adapted from plan §4) + deployment diagrams (local Compose vs free-tier).

**Files:** `infra/docker/*.Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`, `renovate.json` or `.github/dependabot.yml`, `docs/adr/ADR-00{1..8}-*.md`, `docs/architecture/overview.md`

**Tests:** CI itself: open a PR and every job must pass.

**Done when**
- A PR shows all CI jobs green.
- `docker build --target api` works, and `docker run -p 8000:8000` serves `/health/live`.
- ADR-001…008 are merged.

**Pitfalls:** don't bake ML models into the image yet (size). Shell scripts must be LF. Keep CI under ~10 minutes with caching.

**Close-out:** update `agent.md` §9.1 statuses. Commit `ci: add CI pipeline, Dockerfiles and ADRs 001-008`.

---

### Session 05 — Design system foundation (FE-0) → **G0**

**Refs:** §5.5, §27.1, §27.3, §27.20.1–27.20.2, §27.20.9, §27.24, §27.27, §27.28, §27.30 (FE-0) · **Depends on:** 01 (can run parallel to 02–04)

**Goal:** the "Knowledge Instrument" visual system (tokens, typography, motion and restyled accessible primitives) so no screen ever looks like a stock template.

**Tasks**
- [ ] `apps/web/styles/tokens.css`: every token group from plan §27.28:
  - colors: light + dark from §27.3, applied via `[data-theme]` and `prefers-color-scheme`
  - typography scale, spacing scale, radius (controls 7–9 px, panels 10–12 px), borders, elevation (subtle, transient surfaces only), z-index
  - pane dimensions (`sidebar-expanded: 236`, `sidebar-collapsed: 64`, `evidence-default: 400`, `reading-max: 780`), control heights (28/34/40), density modes via `[data-density]`
- [ ] Tailwind mapping of tokens (`@theme`). Add a CI check (small script or ESLint rule) that fails on raw hex colors inside `features/` and `components/`.
- [ ] Fonts with `next/font`: Instrument Sans (UI), Source Serif 4 (reading), IBM Plex Mono (IDs/scores), all with fallbacks. Add a tabular-numerals utility.
- [ ] Motion: `lib/motion/tokens.ts` (durations + easings from §27.20.2), `components/motion/` helpers (fade/slide presets, presence wrapper), root `<MotionConfig reducedMotion="user">`.
- [ ] shadcn/ui initialised into `components/primitives/` and **restyled** (about 15–20 primitives): Button (primary/secondary/ghost/danger, not pill-shaped), IconButton (requires `aria-label`), Input, Textarea, Select, Checkbox, Switch, Tabs (animated indicator via `layoutId`), Dialog, Sheet/Drawer, Popover, Tooltip, DropdownMenu, StatusBadge (semantic color **plus** icon/text), Skeleton, Toast (sonner, restyled), Table base, Kbd, Separator.
- [ ] Icons: `lucide-react`. Write `docs/architecture/frontend-design.md` with the icon policy (no sparkles, wands or robot heads) and the anti-patterns from §27.1.
- [ ] Theme toggle (light/dark/system) persisted in localStorage. Skip-link component. Focus-visible ring tokens.
- [ ] `/dev/primitives` route (dev only, disabled in production builds) showing every primitive in both themes and both densities.
- [ ] Contrast check for every text/background token pair (script or documented table), adjusted to WCAG 2.2 AA.

**Files:** `apps/web/styles/{tokens.css,globals.css}`, `apps/web/lib/motion/*`, `apps/web/components/{primitives,motion}/*`, `apps/web/app/dev/primitives/page.tsx`, `docs/architecture/frontend-design.md`

**Tests:** accessible names on IconButton · Tabs keyboard navigation · axe check (`vitest-axe`) on the primitives page · reduced-motion test (mock `matchMedia`) proving large transforms are disabled.

**Done when**
- `/dev/primitives` looks like the plan's "Knowledge Instrument" direction in light and dark, with no stock shadcn look.
- Keyboard focus is visible on every control, reduced motion works, and the contrast table passes AA.
- **G0 checklist (§6) passes:** local stack, CI green, reproducible migration, design foundation.

**Close-out:** mark G0 in `agent.md` §6. Commit `feat(web): design tokens, motion system and core primitives (FE-0)`. Tag `gate-G0`.

---

## Sprint 1 — Identity, tenancy & authorization (plan Phase 1, FE-1) → G1

### Session 06 — Identity & organization schema

**Refs:** §7.1, §7.2, §7.9 (`audit_events`), §7.10, §8.1 · **Depends on:** 03

**Goal:** the identity, organization and authorization tables with seeded default roles and permissions.

**Tasks**
- [ ] SQLAlchemy models + migration `0002`:
  - `users` (`external_subject` + `issuer` unique, `email`, `display_name`, `status`, `created_at`, `last_seen_at`)
  - `organizations` (`name`, `slug` unique, `status`, `settings_json`)
  - `roles` (`organization_id` NULL for system roles, `key`, `name`) and `role_permissions` (`role_id`, `permission`)
  - `memberships` (unique `(organization_id, user_id)`, `role_id`, `status`, `joined_at`)
  - `groups` (unique name per org) and `group_memberships` (with `organization_id` for RLS)
  - `audit_events` (append-only)
  - `api_keys` (`prefix` unique, `secret_hash`, `organization_id`, `scopes text[]`, `created_by`, `expires_at`, `last_used_at`, `revoked_at`)
  - `invitations` (`organization_id`, `email`, `role_id`, `token_hash`, `expires_at`, `accepted_at`, `invited_by`)
- [ ] `app/auth/permissions.py`: the permission catalogue from §7.2 as constants/enum and the default role → permission mapping for `owner`, `admin`, `knowledge_manager`, `member`, `viewer`.
- [ ] Idempotent seed (migration data step or `app/db/seed.py`) for system roles and permissions.
- [ ] Indexes per §8.1 for these tables.
- [ ] Grants: the owner role owns the tables. The app role gets only the DML it needs. `audit_events` gets INSERT + SELECT only, and a trigger rejecting UPDATE/DELETE as defence in depth.
- [ ] Domain schemas (`app/domain/`) and a repository/service pattern (`app/services/`).

**Tests:** migration up/down · unique constraints · seed idempotency (run twice) · the app role cannot UPDATE/DELETE `audit_events` · role→permission mapping table test.

**Done when:** `make migrate` creates the schema, the 5 system roles have exactly the §7.2 permissions, and tests are green.

**Pitfalls:** put `organization_id` on **every** tenant-scoped table (including join tables) now, because the plan forbids retrofitting it. System roles (`organization_id IS NULL`) must stay readable once RLS arrives in Session 08.

**Close-out:** commit `feat(api): identity and organization schema`.

---

### Session 07 — OIDC authentication (backend)

**Refs:** §5.6, §26.2 (Identity), §28.2 (Authentication), §30 (JWKS cache) · **Depends on:** 06

**Goal:** the API trusts only correctly signed OIDC tokens and provisions users just in time.

**Tasks**
- [ ] `app/providers/identity/`: `IdentityVerifier` protocol + `OIDCVerifier`:
  - discovery document fetch
  - JWKS cache with TTL and refresh-on-unknown-`kid` (rate-limited)
  - verify signature with an algorithm allowlist (RS256/ES256; reject `none` and HS*), `iss`, `aud`, `exp`, `nbf`, `iat` with ≤ 60 s leeway, required `sub`
  - library: PyJWT[crypto] or joserfc
- [ ] `app/api/dependencies/auth.py` `get_principal`: Bearer parsing → verify → JIT upsert of the user by `(issuer, sub)` (update email/display name; throttle `last_seen_at` writes) → `AuthenticatedUser`. Return 401 + `WWW-Authenticate` on failure and 403 for disabled users.
- [ ] `GET /v1/me`: profile + memberships (org id, name, role, effective permissions).
- [ ] `scripts/get_token.py`: password grant against the **dev** Keycloak realm only (for curl/testing).
- [ ] Test utilities: generate an RSA keypair in tests, serve JWKS through `respx`, `make_token(sub=..., aud=..., exp=...)` helper.
- [ ] Leave a clear extension point for API-key auth (implemented in Session 55).

**Tests:** valid → 200 · expired, wrong `aud`, wrong `iss`, bad signature, `alg=none`, unknown `kid` → 401 · key rotation (new `kid`) succeeds · JIT provisioning creates exactly one user · integration test with a real Keycloak token.

**Done when:** `curl -H "Authorization: Bearer <token for alice>" http://localhost:8000/v1/me` returns Alice, and every negative test passes.

**Pitfalls:** the issuer string must match exactly (`localhost` vs container hostname; that's why `KC_HOSTNAME` was set in S02).

**Close-out:** commit `feat(auth): OIDC JWT verification, JIT provisioning and /v1/me`.

---

### Session 08 — Tenant context, Row-Level Security & permission engine

**Refs:** §3 (principles 2, 3, 9), §7.1, §8.2, §8.3, §28.2 (Authorization), ADR-004 · **Depends on:** 07

**Goal:** tenant isolation enforced twice, in application code **and** in PostgreSQL RLS, failing closed.

**Tasks**
- [ ] Tenant resolution: org-scoped routes take `{org_id}` in the path (or an `X-Organization-Id` header) → verify an active membership → build `RequestContext(user_id, organization_id, role, permissions, principal_tokens, request_id)`.
- [ ] Per-request transaction sets transaction-local context: `SELECT set_config('app.organization_id', :org, true), set_config('app.user_id', :uid, true)`.
- [ ] RLS migration for every tenant-scoped table: `ENABLE ROW LEVEL SECURITY` + `FORCE ROW LEVEL SECURITY`. Policy `USING (organization_id = current_setting('app.organization_id', true)::uuid)` with the same `WITH CHECK`. Special cases:
  - `memberships`: also visible where `user_id = current_setting('app.user_id', true)::uuid` (so "list my orgs" works before an org is chosen)
  - `organizations`: visible when the id matches the context **or** the user has a membership
  - `roles`: system roles (`organization_id IS NULL`) are readable by everyone
  - `users`: global table. Expose only users who share an org with the caller, through service code
- [ ] The runtime connects as `knowledgeos_app` (not owner, `NOBYPASSRLS`). `/health/ready` asserts `rolbypassrls = false` and that the role owns no tables.
- [ ] Fail closed: a missing context makes `current_setting(..., true)` NULL, so zero rows.
- [ ] `app/auth/authorization.py`: `has_permission(ctx, perm)`, FastAPI dependency `require_permission("kb.manage")`, and `principal_tokens(ctx)` → `["user:<id>", "group:<id>"..., "role:<key>", "org:<id>"]` (used for chunk ACLs from Session 23).
- [ ] `tenant_session(org_id, user_id=None)` helper for workers and scripts.
- [ ] Return **404, not 403**, for resources in other orgs so existence doesn't leak.

**Tests**
- Integration: with org A context, a query for an org B row by its exact id returns nothing · no context returns nothing · INSERT with a foreign `organization_id` is rejected by `WITH CHECK` · the app role cannot bypass RLS.
- Hypothesis: random role/permission sets → `require_permission` decisions always match the role table.
- API: an org A user calling org B routes gets 404.

**Done when:** the tenant-isolation suite passes at both API and repository level. This is the core of G1.

**Pitfalls:** connection pools leak session-level settings, so use only `set_config(..., true)` inside transactions. Table owners bypass RLS unless `FORCE`. Set `expire_on_commit=False` on async sessions.

**Close-out:** commit `feat(auth): tenant context, row-level security and permission engine`.

---

### Session 09 — Organization, member, group & invitation APIs + audit

**Refs:** §7.9 (audit), §26.1, §26.2 (Identity/org), §27.16, §28.2 (Audit) · **Depends on:** 08

**Goal:** organizations can be created and administered through the API, with every administrative change audited.

**Tasks**
- [ ] Endpoints:
  - `GET/POST /v1/organizations` (the creator becomes owner)
  - `GET /v1/organizations/{org_id}/members` (cursor pagination)
  - `POST .../invitations` (token stored hashed; returns a copyable accept link; email through Mailpit locally is optional) and `POST /v1/invitations/{token}/accept`
  - `PATCH .../members/{user_id}` (role change; the last owner cannot be demoted or removed) and `DELETE .../members/{user_id}`
  - `GET/POST .../groups`, `PATCH/DELETE .../groups/{id}`, `POST/DELETE .../groups/{id}/members`
- [ ] Cursor pagination utility (opaque base64 of `(created_at, id)`) with a page-size cap.
- [ ] Idempotency: `idempotency_keys` table (org-scoped, request hash, response snapshot, TTL) + a dependency for important POSTs.
- [ ] Audit service `audit.record(ctx, action, resource_type, resource_id, metadata)` written **in the same transaction**. Actions: `org.created`, `member.invited`, `member.joined`, `member.role_changed`, `member.removed`, `group.created/updated/deleted`, `group.member_added/removed`.
- [ ] Stable error-code catalogue in `docs/api/errors.md`.

**Tests:** a member cannot manage members · last-owner protection · IDOR (an org B group id → 404) · pagination has no duplicates/skips with concurrent inserts · idempotent replay returns the identical response · every mutation writes exactly one audit row.

**Done when:** the full org/member/group/invitation lifecycle works through the API, is audited, and is documented in OpenAPI.

**Close-out:** commit `feat(api): organizations, members, groups, invitations and audit events`.

---

### Session 10 — Frontend auth, API client & application shell (FE-1 part 1)

**Refs:** §5.5, §5.6, §27.4, §27.5, §27.26, §27.27, §28.2 · **Depends on:** 05, 09

**Goal:** users sign in with OIDC and land in the real application shell, backed by a typed API client.

**Tasks**
- [ ] **Auth.js (v5)** with a generic OIDC provider (Keycloak locally, Auth0 later by changing env only). JWT session strategy holding access/refresh tokens in the encrypted session cookie. Refresh-token rotation. Secure cookie flags. Middleware protecting app routes. Styled sign-in and sign-out pages.
- [ ] **API call pattern (decide and document in an ADR note):** the browser calls FastAPI directly with the short-lived access token from the Auth.js session (kept in memory, never in localStorage), under a strict CORS allowlist on the API. This keeps SSE streaming simple on free hosting and means the API uses no cookies, so no CSRF surface.
- [ ] Typed client: `openapi-typescript` → `packages/contracts/src/schema.d.ts` + `openapi-fetch` wrapper in `lib/api/`. Script `pnpm gen:api` that exports OpenAPI with `uv run python -m app.export_openapi`. CI drift check (regenerate, then `git diff --exit-code`).
- [ ] TanStack Query provider, query-key conventions, Zod parsing of the error envelope.
- [ ] Shell per §27.5:
  - top bar: org/workspace switcher from `/v1/me`, global search trigger, status-center icon, user menu with theme toggle
  - left nav rail per the §27.4 IA, role-aware via permissions, collapsible to an icon rail (persisted)
  - main canvas, plus route stubs for Home, Ask, Search, Knowledge (Libraries, Documents, Sources), Projects, Evaluate, Observe, Access, Settings
- [ ] Org context in the URL (`/[org]/...`), resolved to an org id through memberships. The backend always authorizes by id, never by slug.
- [ ] `lib/permissions`: UI visibility helper (the backend still enforces).
- [ ] "Create your organization" screen for users without memberships (onboarding step 1).

**Tests:** permission-helper unit tests · error-envelope parsing · nav visibility by role (component test).

**Done when:** log in as Alice → the shell shows real memberships → you can create an org → logout works → token refresh works after expiry (temporarily shorten the Keycloak token lifetime to test).

**Pitfalls:** Auth.js v5 env names (`AUTH_SECRET`, `AUTH_URL`, provider vars). The issuer must be reachable from both the Next.js server and the browser.

**Close-out:** commit `feat(web): OIDC login, typed API client and application shell (FE-1)`.

---

### Session 11 — Shell completion: command palette, evidence rail, access pages (FE-1 part 2) → **G1**

**Refs:** §27.5, §27.16, §27.20.3–27.20.4, §27.21, §27.23, §27.24, §27.29, §27.30 (FE-1 exit) · **Depends on:** 10

**Goal:** a complete, keyboard-friendly, responsive shell with basic member and group administration and an E2E test harness.

**Tasks**
- [ ] Command palette (`cmdk`), `Ctrl/Cmd+K`: pages now; documents, KBs and projects plug in later through providers. Admin actions filtered by role. Active item uses a shared-layout indicator.
- [ ] Evidence rail container: right pane controlled by URL/state. Resizable by pointer **and** keyboard (`role="separator"` with arrow keys and `aria-valuenow`). Width persisted per user. The center canvas must not jump when it opens.
- [ ] Responsive modes from §27.5: ≥ 1440 three-pane · 1024–1439 overlay/drawer · 768–1023 collapsed nav + full-height sheet · < 768 mobile task flow.
- [ ] Status center popover (event list, placeholder source for now) and the toast policy helper (§27.23).
- [ ] Shortcut registry + help dialog (`?`), `/` focuses search, `Esc` closes overlays.
- [ ] Access pages (basic): Members (list, invite, change role, remove) and Groups (list, create, manage members) using the Session 09 APIs. The full permission editor comes in Session 52.
- [ ] Route transitions (opacity ≤ 220 ms) and `AnimatePresence` for drawers. Skip links and landmarks.
- [ ] Playwright under `tests/e2e/`: global setup logs in through the Keycloak UI and stores `storageState` per test user. Journeys: login → shell · Carol (Globex) never sees Acme in the switcher, and a direct Acme URL shows not-found.
- [ ] Playwright + axe on shell routes. A CI job runs E2E against the Compose `core` stack.

**Tests:** shortcut registry and resize-handle keyboard (Vitest) · the E2E journeys above.

**Done when** — **G1 checklist:** S08 isolation suite green · members and groups manageable from the UI · keyboard navigation and responsive pane behaviour verified · Playwright login and isolation journeys green in CI.

**Close-out:** mark G1. Commit `feat(web): command palette, evidence rail, access pages and e2e harness`. Tag `gate-G1`.

---

## Sprint 2 — Knowledge bases & secure upload (plan Phase 2, FE-2 part 1) → G2

### Session 12 — Knowledge base & document schema + KB APIs

**Refs:** §7.3, §7.4, §7.5, §8.1, §8.3, §26.2 (Knowledge bases) · **Depends on:** 09

**Goal:** the knowledge, document, version, ACL, job and outbox tables, plus knowledge-base CRUD with access control.

**Tasks**
- [ ] Migration (all with `organization_id` + RLS + indexes):
  - `knowledge_bases`, `knowledge_base_acl`
  - `data_sources` (an `upload` source is auto-created per KB), `source_objects`
  - `documents`, `document_versions` (unique `(document_id, version_number)`), `document_acl`
  - `uploads` (`id`, `kb_id`, `created_by`, `filename`, `declared_mime`, `declared_size`, `object_key`, `status`, `expires_at`)
  - `ingestion_jobs` (§7.5 + `stage_checkpoints jsonb`, `lease_owner`, `lease_expires_at`)
  - `outbox_events` (§7.5 + `available_at`, `last_error`)
  - `knowledge_bases.active_index_generation_id` and `active_rag_profile_version_id` as nullable columns. Their FKs are added in Sessions 19 and 27.
- [ ] KB service + endpoints: `GET /v1/knowledge-bases` (only KBs the caller may query), `POST` (`kb.create`; visibility `organization|restricted`), `GET/PATCH/DELETE /{kb_id}` (delete = archive), `GET/PUT /{kb_id}/permissions` (allow-only ACL; principals must belong to the org).
- [ ] `kb_access(ctx, kb)`: `organization` visibility → every member with `query.execute`; `restricted` → ACL match on user/group/role tokens; manage → `kb.manage` or a `manage` ACL entry.
- [ ] Document-ACL validator: a document ACL may only **narrow** access, never widen a restricted KB (§7.3).
- [ ] `effective_access_principals(kb, document)` stub returning the principal tokens that will be copied onto chunks (finished in Session 23).
- [ ] Audit KB create/update/archive/permission changes. Emit an `acl.changed` outbox event on permission change (consumed in Session 23).
- [ ] **Meta-test:** every table with an `organization_id` column has `relrowsecurity` and `relforcerowsecurity` true (query `pg_class`). This guards all future sessions.

**Tests:** KB CRUD · restricted KB invisible to non-ACL members (list and get → 404) · foreign principal rejected · document-ACL widening rejected · RLS isolation for all new tables · the meta-test.

**Done when:** the KB lifecycle and permissions work through the API, and the RLS meta-test passes.

**Close-out:** commit `feat(api): knowledge bases, document schema and KB access control`.

---

### Session 13 — Object storage & secure upload flow

**Refs:** §5.2, §9.1, §9.3, §25 (ObjectStore), §26.2 (Upload/documents), §34.4 · **Depends on:** 12

**Goal:** browsers upload directly to a quarantine bucket through presigned URLs. Completion atomically creates the document version, job and outbox event.

**Tasks**
- [ ] `app/providers/storage/`: `ObjectStore` protocol (`presign_put`, `head`, `get_stream`, `put`, `copy`, `delete`, `exists`) · `S3ObjectStore` (aioboto3, or boto3 in a thread pool; path-style option for MinIO/B2; **separate public endpoint for presigning** vs internal endpoint for server calls) · `InMemoryObjectStore` for unit tests.
- [ ] Key scheme (never user filenames): quarantine `{org}/{kb}/{upload_id}/original` · trusted `{org}/{kb}/{document_id}/{version_id}/original` · artifacts `{org}/{kb}/{document_id}/{version_id}/canonical.json`.
- [ ] `POST /v1/knowledge-bases/{kb_id}/uploads`: `document.upload` + KB access, extension allowlist (§5.3), declared size ≤ limit → `uploads` row + presigned PUT (10–15 min expiry, content type bound).
- [ ] `POST /v1/uploads/{upload_id}/complete` (`Idempotency-Key`): HEAD the object (exists, size matches declared and is within the limit) → **one transaction**: `documents` (or a new version when replacing), `document_versions` (`version_number = max + 1`, `integrity_status = pending`, `ingestion_status = received`), `ingestion_jobs` (`RECEIVED`), `outbox_events` (`ingestion.requested`), audit event.
- [ ] Replacement start `POST /v1/documents/{id}/versions` (returns a presign) · `GET .../documents` (cursor, filters: status/type/classification) · `GET /v1/documents/{id}` · `GET .../versions` · `GET /v1/ingestion-jobs/{job_id}` · `DELETE /v1/documents/{id}` (marks archived and non-retrievable now; the full cascade comes in Session 49).
- [ ] Store provenance fields (§9.3).
- [ ] `scripts/upload_file.py` for manual testing.

**Tests:** unit tests with the in-memory store · integration with MinIO: presign → `httpx` PUT → complete → rows + outbox exist · injected failure mid-transaction → nothing persisted · size mismatch → rejected · double complete → idempotent · cross-org upload id → 404.

**Done when:** `scripts/upload_file.py` creates a document version, a queued job and an outbox row against the local stack.

**Pitfalls:** presigned URLs must use the browser-reachable host (`localhost:9000`, not `minio:9000`). Presigned PUT cannot enforce size, which is why `complete` HEAD-verifies and the worker re-validates.

**Close-out:** commit `feat(api): object storage provider and secure upload flow`.

---

### Session 14 — File-safety validation & malware scanning

**Refs:** §9.2, §28.2 (Uploads), §39.4 (zip bomb, overlarge file) · **Depends on:** 13

**Goal:** a strict, well-tested validation module and malware-scanner interface, ready for the worker stage in Session 17.

**Tasks**
- [ ] `app/security/file_validation.py` (pure functions over byte streams, never raises on garbage input):
  - MIME sniffing from bytes (`puremagic`/`filetype`, pure Python and Windows-friendly) + extension/MIME consistency matrix for the §5.3 formats
  - reject executables and scripts (PE/ELF/Mach-O headers, shebangs, `.exe/.dll/.js/.vbs/.ps1/.bat/.jar`…)
  - OOXML (zip) checks: entry count, total uncompressed size, per-entry compression ratio (zip bomb), nested archives, path traversal names, macros (`vbaProject.bin`, `.docm/.xlsm/.pptm` rejected in v1)
  - PDF: encrypted → policy reject, page-count limit, flag `/JS`, `/OpenAction`, `/Launch` (pypdf)
  - images: pixel/dimension limits (Pillow `MAX_IMAGE_PIXELS`, decompression-bomb errors handled), TIFF page limit
  - CSV/text: encoding detection (`charset-normalizer`), size/line limits
  - streaming SHA-256
  - duplicate detection **within the same KB only** (§9.2)
- [ ] `ValidationResult(status: accepted|rejected|flagged, reasons: [codes], detected_mime, sha256)` with stable codes.
- [ ] `app/providers/scanning/`: `MalwareScanner` protocol · `ClamAVScanner` (clamd `INSTREAM` over TCP, timeout, size cap) · `NoopScanner` (logs a warning and marks `scan_skipped`). Setting `require_malware_scan` (true in staging/prod) makes skipped scans fail.
- [ ] Fixtures: tiny valid samples per format committed. **Malicious samples are generated at test runtime, never committed:** EICAR string, zip bomb, `.exe` renamed to `.pdf`, encrypted PDF, macro `.docm`, oversized sparse file, polyglot.

**Tests:** one unit test per check · Hypothesis: random bytes always produce a `ValidationResult` (no exceptions) · integration (`full` profile): ClamAV detects EICAR.

**Done when:** every malicious fixture is rejected with the right code, every valid fixture is accepted, and the validator is callable from a worker stage.

**Pitfalls:** **Windows Defender deletes EICAR and zip-bomb files on disk**, so generate them in memory or inside containers.

**Close-out:** commit `feat(security): file validation and malware scanning`.

---

### Session 15 — Knowledge library & upload UI (FE-2 part 1) → **G2**

**Refs:** §27.9, §27.9.2, §27.22 (empty KB), §27.25, §27.30 (FE-2) · **Depends on:** 11, 13

**Goal:** users manage knowledge bases, browse documents in a dense table, and upload files that show a live pipeline.

**Tasks**
- [ ] Knowledge → Libraries: KB list (name, visibility, document count, updated), create dialog, KB settings page (general + read-only permissions view).
- [ ] Documents library: TanStack Table + TanStack Virtual with the §27.9.1 columns (placeholders where data comes later). Sticky header, server-side sorting, column visibility, density toggle, filters, cursor "load more", bulk select (archive action), row preview in the evidence rail, URL state for filters and the selected document.
- [ ] Upload: drop zone + picker, multiple files, client-side size/extension checks, presign → **XHR PUT with progress** (fetch has no upload progress) → complete.
- [ ] Pipeline component (Uploaded / Scanning / Parsing / Chunking / Embedding / Indexing / Permission map) driven by polling `GET /v1/ingestion-jobs/{id}` with backoff. Jobs stay visible in the status center when the user navigates away.
- [ ] Empty KB state (§27.22) explaining what happens after adding knowledge.

**Tests:** job state/stage → pipeline step mapping (Vitest) · column-visibility persistence · Playwright: create KB → upload PDF → row appears with a queued state.

**Done when** — **G2 checklist:** a valid file → durable document version + queued job (visible in UI and DB) · malicious and unsupported fixtures fail safely (validator tests + API rejections with stable codes). Jobs staying in `RECEIVED` is expected; the worker arrives in Sprint 3.

**Close-out:** mark G2. Commit `feat(web): knowledge library, documents table and upload flow (FE-2a)`. Tag `gate-G2`.

---

## Sprint 3 — Reliable ingestion (plan Phase 3, FE-2 part 2) → G3

### Session 16 — Outbox dispatcher, Celery & ingestion job state machine

**Refs:** §4.1 (dispatcher, worker), §14, §14.1, §34.2, §34.4, ADR-005 · **Depends on:** 13

**Goal:** database changes reliably become background work, and every ingestion job moves through an explicit, idempotent, resumable state machine.

**Tasks**
- [ ] `app/workers/celery_app.py`: Redis broker, `task_acks_late=True`, `task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`, JSON serializer only, soft/hard time limits, queues `ingestion`, `sync`, `maintenance`, `eval`, `llm`.
- [ ] Dispatcher `python -m app.workers.dispatcher`: loop over `SELECT … FROM outbox_events WHERE published_at IS NULL AND available_at <= now() ORDER BY created_at LIMIT 100 FOR UPDATE SKIP LOCKED` → publish the Celery task → set `published_at`. On failure, increment `attempt_count` and push `available_at` back with backoff.
  - Cross-tenant access with least privilege: connect as `knowledgeos_dispatcher`, whose RLS policy allows only `outbox_events` (`CREATE POLICY … TO knowledgeos_dispatcher USING (true)`). Document this in ADR-004.
  - Store the W3C `traceparent` in the event payload now (used in Session 43).
- [ ] `app/ingestion/state_machine.py`: the §14 states and stages plus `PENDING_APPROVAL`, `QUARANTINED`, `FAILED_RETRYABLE`, `FAILED_PERMANENT`, `CANCELLED`. An explicit allowed-transition table. `advance(job, to)` with guards. Persist `stage`, `progress_percent`, `heartbeat_at`, `attempt_count`, `error_code`, `error_detail_safe`, `stage_checkpoints`.
- [ ] Concurrency safety: a **lease** on the job row (`lease_owner`, `lease_expires_at`, claimed with `UPDATE … WHERE lease_expires_at < now()`), because a job spans several transactions. Plus a transaction-scoped advisory lock keyed by `(document_version_id, index_generation_id)` around write stages.
- [ ] Stage runner: each stage is a function `(ctx, job, checkpoint) → checkpoint`. Stages with an existing checkpoint are skipped (resume after a crash). Heartbeats every N seconds during long stages.
- [ ] Error classes: `RetryableError` (timeouts, network, 5xx/429) vs `PermanentError` (validation rejection, unsupported). Exponential backoff + jitter, max attempts, then `FAILED_PERMANENT`.
- [ ] **Stub (no-op) implementations for every stage** so a job can reach `READY` end to end.
- [ ] Compose (`full` profile): `worker`, `dispatcher`, `beat` services built from the backend image. Makefile `worker`, `dispatcher`.

**Tests:** transition table (illegal transitions raise) · backoff maths · integration: outbox event → dispatcher → worker → job `READY` · duplicate outbox delivery has a single effect · two workers racing for one job → only one runs · simulated crash between stages resumes from the checkpoint.

**Done when:** an upload from the UI reaches `READY` through the stub stages, and the UI pipeline shows the progression.

**Pitfalls:** Celery's prefork pool doesn't work on Windows, so run workers in Docker only. Celery tasks are sync: wrap async code with `asyncio.run(...)` and create the DB engine **after fork** (`worker_process_init` signal).

**Close-out:** commit `feat(ingestion): outbox dispatcher, celery workers and job state machine`.

---

### Session 17 — Validation stages, canonical document model & Docling parsing

**Refs:** §5.3, §9.1 (step 8), §9.2, §10.1, §10.2 (PDF, DOCX, HTML, Markdown), §14 · **Depends on:** 14, 16

**Goal:** real VALIDATING, MALWARE_SCAN and PARSING stages producing a persisted canonical document artifact.

**Tasks**
- [ ] **VALIDATING:** stream the quarantined object → `file_validation` (S14) → write `sha256`, `mime_type`, `integrity_status`. In-KB duplicate check. Rejection → `FAILED_PERMANENT` with a safe error code.
- [ ] **MALWARE_SCAN:** ClamAV. Infected → `QUARANTINED` + audit event (the object stays in quarantine for forensics). Clean → copy to the trusted bucket key, delete the quarantine object, update `object_key`.
- [ ] `app/ingestion/canonical.py`: Pydantic `CanonicalDocument` (§10.1) with `schema_version`, `title`, `languages`, `metadata`, and `blocks[]` (`block_id` as a stable hash, `type` ∈ heading|paragraph|list|table|code|caption|image_text|furniture, `text`, structured `table`, `page`, `bbox`, `heading_path`, `source_order`, `extra` for slide/sheet/row range/OCR confidence).
- [ ] Parser interface `DocumentParser` + `DoclingParser` for PDF (native text), DOCX, HTML and Markdown: map Docling items to blocks with page numbers, bounding boxes, heading hierarchy, structured tables and reading order. Record `parser_name` and `parser_version`.
- [ ] Isolation: run parsing in a **subprocess** with a wall-clock timeout and memory limit (`resource.setrlimit(RLIMIT_AS)` inside the Linux container). Kill on timeout → retry once → `FAILED_PERMANENT`.
- [ ] **PARSING** writes `canonical.json` to the artifacts bucket and sets `canonical_artifact_key` + a checkpoint.
- [ ] Worker image: CPU-only PyTorch wheels (configure the uv index for `https://download.pytorch.org/whl/cpu`). Pre-download Docling models at build time.

**Tests:** golden fixtures (PDF with headings + table, DOCX with lists + table, HTML with nav boilerplate, Markdown with code) → **snapshot tests** (syrupy) on block types, heading paths and pages · simulated parser hang → timeout path · infected file → `QUARANTINED`.

**Done when:** uploading PDF/DOCX/HTML/MD produces a canonical artifact in MinIO, and the job continues to the (stub) later stages.

**Pitfalls:** the first Docling run downloads models and is slow, so give the worker ≥ 4 GB RAM. Pin the Docling version because its output changes between releases.

**Close-out:** commit `feat(ingestion): validation, malware scan, canonical model and docling parsing`.

---

### Session 18 — Office & tabular formats, OCR & normalization

**Refs:** §5.3, §10.2 (PPTX, XLSX/CSV, HTML, images), §10.3 · **Depends on:** 17

**Goal:** every first-release format (including scans and images) becomes a clean, normalized canonical artifact.

**Tasks**
- [ ] **PPTX:** one logical unit per slide (title + body + speaker notes) with `slide_number`.
- [ ] **XLSX/CSV:** openpyxl (`read_only=True`, `data_only=True`; formulas never executed) and the csv sniffer. Sheet name, header-row detection, row groups (≈ 20–50 rows) serialized as table blocks **with headers repeated**, `row_range` metadata, row/column caps. Mark the metadata so the UI can say text RAG is not analytics (§10.2).
- [ ] **Plain text:** encoding detection, paragraph splitting.
- [ ] **HTML:** boilerplate removal (navigation, cookie banners, footers), keep canonical URL, title, headings, useful tables and code (reused by the web connector in Session 50).
- [ ] **OCR:** detect scanned PDF pages (no or very little text layer) → Docling OCR pipeline (Tesseract or RapidOCR for CPU; install language packs in the image). Images PNG/JPEG/TIFF → OCR. Record per-block `ocr_confidence` and flag low confidence for diagnostics.
- [ ] **NORMALIZING** stage (`app/ingestion/normalize.py`):
  - Unicode **NFC** (not NFKC, which can change legally meaningful text)
  - whitespace normalization outside table/code blocks
  - removal of zero-width and bidi-override characters, keeping a forensic `raw_text` copy when policy requires
  - language detection per document/block (`lingua-language-detector`)
  - repeated header/footer detection across PDF pages → `type = furniture` (excluded from chunks)
  - bump `normalization_version` in the artifact

**Tests:** snapshots for PPTX with notes, XLSX with two sheets, semicolon CSV, a scanned PDF (generated from rendered text), a PNG with text (fuzzy word match) · normalization unit tests (zero-width, bidi, header/footer) · language detection for English + one other language used in the corpus.

**Done when:** all plan §5.3 core formats produce canonical artifacts. That is the format half of G3.

**Pitfalls:** OCR is CPU-heavy, so enforce page limits. openpyxl must be in read-only mode for big files.

**Close-out:** commit `feat(ingestion): office and tabular formats, OCR and normalization`.

---

### Session 19 — Content-security scanner, approval flow & structure-aware chunker

**Refs:** §7.6 (schema), §9.3 (approval), §11, §12, §13.2 · **Depends on:** 18

**Goal:** canonical content is scanned for injection and abuse patterns, optionally approved, and split into structure-aware parent/child chunks.

**Tasks**
- [ ] **SECURITY_SCAN** (`app/security/content_scanner.py`), rules configured in `configs/policies/content_scan.yaml`:
  - injection phrases (multilingual list: "ignore previous instructions", "you are now", "system:", chat-template tokens, "### Instruction")
  - fake role/system message markers
  - zero-width/bidi density
  - long base64/hex blobs
  - suspicious links (`javascript:`, `data:`, IP-literal hosts, punycode look-alikes)
  - repetition dominance (n-gram flooding)
  - content-type mismatch flags from Session 14
  - Score → outcome `clean | flagged | quarantined | rejected`. Store findings as block ids + rule ids (never full text in logs).
- [ ] Approval: sources with `trust_level` untrusted/high-risk, or `flagged` content where policy demands it → `PENDING_APPROVAL`. Endpoints `POST /v1/documents/{id}/versions/{vid}/approve|reject` (`document.publish`) with reason and audit.
- [ ] Migration: `index_generations` (§7.6) and `chunks` (§7.6 core columns: content, `content_hash`, `token_count`, `ordinal`, `parent_chunk_id`, `block_type`, `section_path`, `page_start/end`, `bbox_json`, `metadata_json`, `visibility`, FKs). Unique `(document_version_id, index_generation_id, ordinal)`. Add the FK `knowledge_bases.active_index_generation_id`. Auto-create generation #1 (`active`) per KB. `embedding`, `search_vector` and `access_principals` arrive in Session 23.
- [ ] `app/ingestion/chunking/structure_aware.py`:
  - tokenizer = the embedding model's tokenizer (Qwen3 via `tokenizers`)
  - group blocks into sections by heading path; parent sections bounded at ~1,500–2,500 tokens
  - child chunks ~600 tokens; a heading is never separated from its content; ~80-token overlap only where no structural boundary exists; minimum ~80 tokens (merge small chunks within the same section)
  - tables split by rows with the header repeated; code blocks kept whole (split by lines only if huge)
  - page/slide/row ranges aggregated; `furniture` blocks skipped
  - `content_hash` (SHA-256); `embedding_text` = title + section path + labels + body (§12.3)
  - chunker name/version/config recorded on the generation
- [ ] Alternative `recursive_fixed` chunker behind the same interface (for experiments, §12.4).
- [ ] **CHUNKING** stage: delete-then-insert inside one transaction for `(version, generation)`, so it is idempotent.

**Tests:** one test per scanner rule · a poisoned fixture is flagged · approval flow · **Hypothesis invariants for the chunker:** every non-furniture block's text appears in at least one child; no chunk exceeds the max (except a flagged unsplittable unit); no chunk ends with a heading lacking body; table chunks include the header; ordinals are contiguous; output is deterministic · re-running CHUNKING never duplicates rows.

**Done when:** uploaded documents end with persisted chunks (no embeddings yet) and scanner outcomes, and the poisoned document is flagged.

**Close-out:** commit `feat(ingestion): content security scanner, approval flow and structure-aware chunker`.

---

### Session 20 — Ingestion reliability & recovery

**Refs:** §14.1, §34.1–34.4, §39.5, §41 (Demo 12) · **Depends on:** 19

**Goal:** ingestion survives worker crashes, stuck jobs and lost messages, and failures can be retried precisely.

**Tasks**
- [ ] Reconciliation task (Celery beat, every 1–5 min):
  - non-terminal jobs with a stale heartbeat → requeue (`attempt + 1`) or `FAILED_RETRYABLE`
  - outbox events published long ago whose job never started → republish
  - expired, never-completed uploads → mark expired and delete the quarantine object
  - long-waiting `PENDING_APPROVAL` → status-center reminder event
- [ ] Beat schedules in `app/workers/schedules.py` (exactly one beat instance).
- [ ] `POST /v1/ingestion-jobs/{id}/retry`: resumes from the failed stage using checkpoints · `POST /v1/documents/{id}/reindex`: re-runs from the canonical artifact (chunking onward) · `POST /v1/ingestion-jobs/{id}/cancel` → `CANCELLED`.
- [ ] `ingestion_job_events` table (job, time, state, stage, safe message) for the diagnostics timeline.
- [ ] Progress: stage weights → `progress_percent`. `GET /v1/knowledge-bases/{kb}/ingestion-jobs?state=active|failed`. Polling with ETag is fine; SSE is optional.
- [ ] Explicit connect/read/total timeouts on every external call (object store, clamd).
- [ ] Crash test `tests/integration/test_worker_crash.py`: run a real worker container, upload a large document, `docker kill` the worker mid-stage, restart it, and assert the job reaches `READY` with **exactly** the chunk count of a clean run.
- [ ] `scripts/demo_worker_crash.sh` (Demo 12).

**Tests:** reconciliation scenarios · retry from the failed stage · cancel · duplicate outbox · crash test.

**Done when:** the crash/restart test passes, and failed jobs show a safe error with a working retry.

**Close-out:** commit `feat(ingestion): reconciliation, retries, cancellation and crash recovery`.

---

### Session 21 — Ingestion UI: live pipeline, diagnostics, document reader & inspect mode (FE-2 part 2) → **G3**

**Refs:** §27.9.2, §27.10, §27.22 (ingestion failure), §27.23, §27.30 (FE-2 exit) · **Depends on:** 15, 20

**Goal:** a user can follow, diagnose and retry a document's whole lifecycle from the UI, and inspect exactly how it was parsed and chunked.

**Tasks**
- [ ] Live pipeline rows: stages update in place with chunk counts (embedding % arrives in Session 22). Failures expand to show stage, safe explanation, retryability and trace/request ID, with a retry button. Completion and failure go to the status center (no toast spam).
- [ ] KB ingestion-jobs view (active/failed filters).
- [ ] Document detail page:
  - **Reader mode:** canonical-block renderer for every format, outline from headings, find-in-document, metadata summary, version state
  - **Inspect mode** (`kb.manage`): version and provenance (SHA-256, parser version, source), canonical block tree, chunk boundaries (token counts, page ranges, section paths), security-scan findings, ingestion timeline from `ingestion_job_events`
- [ ] Approval queue for knowledge managers (approve/reject with reason).
- [ ] Basic PDF preview with `react-pdf`, lazy-loaded (citation anchoring comes in Session 31).

**Tests:** timeline mapping (Vitest) · Playwright: upload → `READY` → open Inspect → chunks listed · a failing fixture shows the error and retry works.

**Done when** — **G3 checklist:** all core formats → canonical artifacts (S17–S18) · worker restart creates no duplicates (S20) · failed jobs diagnosable and retryable from the UI without reading backend logs.

**Close-out:** mark G3. Commit `feat(web): ingestion pipeline, diagnostics and document reader/inspect (FE-2b)`. Tag `gate-G3`.

---

## Sprint 4 — Indexing & retrieval-only search (plan Phase 4, FE-3) → G4

### Session 22 — Index generations & embedding providers

**Refs:** §5.4, §7.6 (`index_generations`), §13, §25, §25.2, §30 · **Depends on:** 19

**Goal:** chunks get 1024-dimension embeddings from a free, local, in-process model, recorded against an explicit index generation.

**Tasks**
- [ ] Index-generation service: KB creation → generation #1 `active` with `embedding_provider`, `embedding_model`, `embedding_dimension = 1024`, chunker config and parser pipeline version from config. Admin endpoint `GET /v1/knowledge-bases/{kb}/index-generations`.
- [ ] `app/providers/embeddings/base.py`: protocol with `embed_documents(texts)`, `embed_query(text)`, `model_id`, `dimension`, `max_batch`, `is_external`.
- [ ] `SentenceTransformersEmbeddingProvider` (**default**): `Qwen/Qwen3-Embedding-0.6B`, query prompt for queries, normalized vectors, configurable batch size, `max_seq_length` cap, CPU device, lazy process-wide singleton, warm-up, and an assertion that output dimension = 1024.
- [ ] `OpenAICompatibleEmbeddingProvider` (TEI/Infinity/Ollama or a hosted endpoint) with an explicit `is_external` flag per config.
- [ ] `FakeEmbeddingProvider`: deterministic hash-based vectors for tests.
- [ ] Embedding reuse inside the security boundary (§13.1): before embedding, reuse vectors from chunks in the **same org** with the same model and `embedding_text` hash.
- [ ] **EMBEDDING** stage: batch-embed chunks lacking vectors (resume-safe), progress updates, retryable on provider errors. **Never fall back to a different model** (§25.2). If the configured provider is unavailable → `FAILED_RETRYABLE`.
- [ ] Model caching: `HF_HOME` volume in Compose + `scripts/download_models.py`. `HF_TOKEN` is optional.
- [ ] INDEXING and VERIFYING stage skeletons (finished in Session 23).

**Tests:** provider contract tests with the fake · `slow`-marked test loading the real Qwen3 model (nightly, not on every PR) · dimension-mismatch guard · no-substitution test · reuse test.

**Done when:** documents in the local stack get 1024-d embeddings, and the generation row records the exact model ID.

**Pitfalls:** CPU throughput is modest, so keep batches small, set `torch.set_num_threads`, and run the embedding queue with concurrency 1–2 to avoid oversubscription.

**Close-out:** commit `feat(rag): index generations and embedding providers`.

---

### Session 23 — Chunk indexing, vector/full-text indexes & ACL materialization

**Refs:** §7.6 (`chunks`), §8.1, §8.3, §8.4, §15.2, §18.2 · **Depends on:** 22

**Goal:** every chunk is searchable by vector and keyword and carries its parent document's authorization metadata.

**Tasks**
- [ ] Migration on `chunks`: `embedding vector(1024)`, `search_vector tsvector` (weighted: title **A**, section path **B**, body **C**), `fts_config regconfig` (per detected language, `simple` fallback), `access_principals text[]`, `identifiers text[]`.
- [ ] Identifier extraction at chunking (e.g. `[A-Z]{2,}-\d+(-[A-Z])?`, clause/section numbers) → `identifiers`.
- [ ] Indexes: HNSW `(embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)` · GIN `search_vector` · GIN `access_principals` · GIN `identifiers` · trigram GIN on title · B-tree `(organization_id, knowledge_base_id, index_generation_id)` and `(document_version_id)`.
- [ ] Retrieval predicate strategy: **join-based first** (chunk → document active version + not archived/deleted; chunk generation = KB active generation) for correctness. Denormalizing a `retrievable` flag is benchmarked in Session 58.
- [ ] `effective_access_principals(document)`: org-visible KB → `["org:<id>"]`, narrowed by a document ACL if present · restricted KB → KB ACL principals ∩ document ACL. Written onto every chunk in INDEXING.
- [ ] `acl.changed` consumer: batch-updates `access_principals` for affected chunks and stamps `acl_propagated_at` on the KB/document (the UI uses it in Session 52 to say "Search index confirmed at …").
  - Group membership and role changes need **no** chunk rewrite, because chunks store group/role tokens and the user's tokens are computed at query time. Document this property.
- [ ] **INDEXING** fills tsvector + ACL. **VERIFYING** checks that every chunk has an embedding, that a self-query by content hash finds the chunk, and then marks the version `READY` and sets `documents.active_version_id` for first versions.

**Tests:** ACL materialization matrix (property-based) · propagation updates chunks · a group-membership change is effective immediately without reindexing · required indexes exist (`pg_indexes`) · `EXPLAIN` shows HNSW for a plain dense query.

**Done when:** `READY` documents are fully indexed (embedding + tsvector + ACL) in the local stack.

**Close-out:** commit `feat(rag): chunk indexing, vector and full-text indexes, ACL materialization`.

---

### Session 24 — Permission-aware hybrid search backend

**Refs:** §8.3, §8.4, §17, §18, §25 (SearchBackend), §25.2, §39.2 · **Depends on:** 23

**Goal:** dense and lexical retrieval with authorization applied **before** ranking, fused with RRF.

**Tasks**
- [ ] `app/providers/search/base.py`: `SearchBackend` protocol (`dense_search`, `lexical_search`, `hybrid_search(request) → HybridResult` with per-branch ranks, scores and latency).
- [ ] `PostgresSearchBackend`:
  - **one mandatory authorization-predicate builder** that callers cannot bypass: organization, allowed KB ids, active generation, active version, not archived/deleted, `access_principals && :principal_tokens`
  - dense: `SET LOCAL hnsw.ef_search`, `SET LOCAL hnsw.iterative_scan = relaxed_order`, `SET LOCAL hnsw.max_scan_tuples`, then `ORDER BY embedding <=> :q LIMIT :k` (k ≈ 50) inside a materialized CTE, re-sorted by distance
  - lexical: `websearch_to_tsquery(cfg, :q)`, `ts_rank_cd`, exact-identifier boost (`identifiers @> …`), title boost, trigram fallback when FTS returns too few results
  - run dense and lexical **concurrently on two connections**, each with the tenant context set
  - degraded mode: if one branch fails and the profile allows it, return the other branch with `degraded` flags (§25.2)
- [ ] `app/rag/fusion/rrf.py`: weighted RRF (`k0 = 60`, dense 0.55, lexical 0.45) as a pure function, dedupe by chunk id, near-duplicate cap by `content_hash`, per-document cap that still keeps same-document continuity.
- [ ] `QueryFilters` (§17) compiled through a field whitelist (never raw SQL). An inferred non-security filter may be relaxed **once** if it causes zero results. Authorization filters are **never** relaxed.

**Tests**
- RRF unit tests with hand-computed expectations.
- **Hypothesis:** for random corpora × ACLs × principals, every returned chunk satisfies the predicate, checked against a brute-force Python filter.
- Integration (real pgvector): restricted chunks are never returned, even for exact-title queries · inactive-generation and archived-document chunks never appear · filtered HNSW recall vs exact search on a ~5k-chunk fixture is ≥ 0.95 with iterative scan.

**Done when:** hybrid search returns correct, authorized results in integration tests.

**Pitfalls:** `SET LOCAL` only works inside a transaction. `relaxed_order` can return slightly unordered rows, so re-sort. asyncpg connections can't run two queries at once, hence two connections.

**Close-out:** commit `feat(rag): permission-aware hybrid search with RRF fusion`.

---

### Session 25 — Search API, demo corpus & Search UI (FE-3)

**Refs:** §7.8 (`query_runs`, `retrieval_hits`), §16.2, §26.2 (`/search`), §27.8, §27.30 (FE-3), §41 (Demos 1, 2, 5, 6) · **Depends on:** 24

**Goal:** a fast, useful enterprise search without generation, on a realistic synthetic demo corpus.

**Tasks**
- [ ] `POST /v1/knowledge-bases/{kb_id}/search` and multi-KB `POST /v1/search`: query normalization (§16.2: trim, NFC, max length, language detection), filters, results with snippets (`ts_headline` for lexical hits, leading passage for semantic-only hits), `match_type` (exact | semantic | both), permitted document metadata and page ranges. Persist `query_runs` (query text only when the retention setting allows; otherwise a hash) and `retrieval_hits`.
- [ ] Demo corpus: original synthetic content generated by `scripts/seed_demo.py` from templates (reportlab / python-docx / openpyxl / python-pptx, so every format is exercised):
  - **Acme Corp**: HR KB (2025 and 2026 handbooks with a changed leave policy; policy code **HR-142-B**; a restricted compensation document visible only to the HR group), Support KB (manual, FAQ, troubleshooting), Engineering KB (runbooks, architecture notes with code), Compliance KB (numbered clauses across pages), one non-English policy, one poisoned document ("ignore previous instructions…")
  - **Globex**: a deliberately similar handbook (tenant-isolation demo)
  - Users: Alice (Acme admin), Bob (Acme member), Hana (Acme HR manager, in the HR group), Carol (Globex admin)
- [ ] Search UI `/[org]/search`: debounced instant results, facets (KB, source, type, owner, updated, classification, verification), highlighted snippets, exact vs semantic badges, ↑/↓/Enter keyboard navigation, preview in the evidence rail, "Ask about these results" (passes document IDs to Ask; wired in Session 30), URL state.

**Tests:** API tests (run persisted; with retention off no query text is stored) · Playwright: **Demo 2** (`HR-142-B` → exact match first) · **Demo 5** (Bob searching the restricted title finds nothing; Hana finds it) · **Demo 6** (Carol searching an Acme phrase finds nothing).

**Done when:** `make seed` builds the full demo, and the Search UI shows sensible exact and semantic results.

**Close-out:** fill `agent.md` §4.6. Commit `feat: search API, demo corpus seed and search UI (FE-3)`.

---

### Session 26 — Retrieval debugger v1 → **G4**

**Refs:** §27.13, §27.20.5, §27.30 (FE-7, debugger part) · **Depends on:** 25

**Goal:** the signature admin screen that shows *why* retrieval returned what it did.

**Tasks**
- [ ] API: `GET /v1/query-runs/{id}` (full detail only with `retrieval.debug`: per-branch ranks and scores, fused score, filters applied, a principal-constraint summary that never lists unauthorized documents, generation id, embedding model, per-stage latency). `debug=true` on search returns the same payload for authorized admins.
- [ ] UI (admin only, **code-split** so it never loads in the employee bundle): query box + KB selector · pipeline stepper `[PLAN] [RETRIEVE] [RERANK] [CONTEXT] [ANSWER]` (later steps fill in Sprint 5) · results inspector (#, source, dense rank/score, lexical rank/score, fused, selected?) · toggles dense/lexical/fused with keyed `layout` rank animation (off with reduced motion or > 50 rows) · chunk preview · metadata panel · deep link by `query_run_id`.
- [ ] Gate script `tests/integration/test_gate_g4.py`: an identifier query hits the top 3 · a paraphrased semantic query hits the top 5 (**Demo 1**) · restricted chunks never appear · junk chunks in a **non-active** second generation never appear.

**Tests:** rank-diff computation (Vitest) · Playwright: an admin sees both branches, a member cannot open the debugger.

**Done when** — **G4 checklist:** exact + semantic retrieval work · restricted chunks never returned · active-generation constraint enforced (gate script green).

**Close-out:** mark G4. Commit `feat: retrieval debugger v1`. Tag `gate-G4`.

---

## Sprint 5 — Reranking, grounded generation & citations (plan Phase 5, FE-4) → G5

### Session 27 — Reranking, RAG profiles & context packing

**Refs:** §7.7, §19, §20, §25 (RerankerProvider), §25.2 · **Depends on:** 24

**Goal:** fused candidates are reranked by a free local cross-encoder and packed into a token-budgeted, aliased evidence set.

**Tasks**
- [ ] `rag_profiles` (§7.7, immutable versions; editing creates a new version) with system preset `default-hybrid-v1`:
  - `dense_k = 50`, `lexical_k = 50`, RRF `k0 = 60`, weights 0.55/0.45
  - `rerank_candidates = 30` (try 20 on CPU), `final_context_k = 8`, `max_context_tokens = 4500`, per-document cap
  - rewrite/decomposition switches, abstention thresholds (placeholders until calibrated in Session 41), `prompt_version`, `allow_degraded_rerank = true`
  - add the FK `knowledge_bases.active_rag_profile_version_id`
- [ ] `model_policies` base table (§7.7): allowed providers per operation, `local_only`, max external classification, primary and fallback generation models, reranker model. Basic checks now; full enforcement in Session 53.
- [ ] Reranker protocol `rerank(query, candidates) → scores` · `CrossEncoderReranker` (`BAAI/bge-reranker-v2-m3` via sentence-transformers, ONNX backend, int8 where available, `max_length` 512, batched) · `FakeReranker`. Hosted rerankers (Cohere/Jina free trials) are optional and marked external.
- [ ] Bounded timeout (configurable CPU budget). On timeout or failure, if the profile allows it, use the fused order and set `degraded.rerank = true` in trace and response.
- [ ] `app/rag/context/packer.py`: token budget, per-document cap, redundancy removal (content hash + shingle Jaccard), neighbor expansion (ordinal ± 1 from the same version/generation, **re-applying the authorization predicate**) for fragmentary chunks.
- [ ] Source aliases `[S1]…[Sn]` with stored metadata (§20.2: chunk id, title, version, page/slide/row range, section path, location, content hash).
- [ ] Measure CPU rerank latency for 20 and 30 candidates and log it in `agent.md` (I-003).

**Tests:** packer (budget, caps, neighbor expansion respects authorization) · alias mapping is stable · degraded path is flagged · profile immutability.

**Done when:** debug search shows rerank scores and the selected context, and the debugger's RERANK and CONTEXT steps are populated (**Demo 3**).

**Close-out:** commit `feat(rag): reranking, RAG profiles and context packing`.

---

### Session 28 — LLM gateway (free providers), grounded generation & citation validation

**Refs:** §16.1, §20.3, §21, §22, §25 (LLMProvider), §25.2, §35, §7.8 (`answers`, `citations`) · **Depends on:** 27

**Goal:** a grounded answer with only valid citations, produced by free models behind one adapter, abstaining when evidence is insufficient.

**Tasks**
- [ ] `app/providers/llm/base.py`: `generate(messages, **params) → LLMResult(text, usage, model, finish_reason)`, `stream(...) → AsyncIterator[LLMChunk]`, `provider_id`, `model_id`, `is_external`.
- [ ] `OpenAICompatibleLLM` (httpx or the `openai` SDK with `base_url`). Config entries: `ollama` (`http://ollama:11434/v1`), `groq` (`https://api.groq.com/openai/v1`), `gemini` (`https://generativelanguage.googleapis.com/v1beta/openai/`), `openrouter` (`https://openrouter.ai/api/v1`). Each has an API-key env var, model id, and RPM/TPM/RPD limits. **Model IDs only in config.**
- [ ] Gateway `app/rag/generation/gateway.py`: per-provider token-bucket throttle in Redis · honour 429 + `Retry-After` · bounded retries with jitter · connect/read/total timeouts · fallback only to policy-allowed compatible models (§25.2) · token usage recorded (estimated when the provider omits it).
- [ ] `FakeLLM` with scripted outputs (valid answer, unknown citation, missing citations, injection-compliant answer) for deterministic tests and CI.
- [ ] Prompt `configs/prompts/grounded_answer/v1.yaml`, loaded by version: the §21.1 contract, evidence wrapped as `<untrusted_evidence id="S1" title="…" page="…">…</untrusted_evidence>`, cite only `[S#]`, an explicit abstention format, conflicts must be mentioned. A few-shot example helps small models.
- [ ] Abstention: **before** generation, with no candidates or a top rerank score below threshold → abstain without calling the LLM and return the closest authorized sources. **After** generation, the model's insufficient-evidence marker → abstain.
- [ ] `app/rag/citations/validator.py`: parse `[S1]` and `[S1, S3]` forms · unknown alias → **one** bounded regeneration with a correction instruction · still invalid → fail safe (no fabricated citations reach the user) · a non-abstained factual answer needs at least one citation · page/section metadata always comes from the stored alias map, never from model text.
- [ ] `POST /v1/knowledge-bases/{kb}/query` (non-streaming): normalize → search → rerank → pack → generate → validate. Persist `query_runs`, `retrieval_hits.selected_for_context`, `answers`, `citations`.
- [ ] No tool calling exists anywhere. Retrieved text can never change instructions or permissions.

**Tests:** validator (unknown, tampered and missing aliases) · regeneration and fail-safe paths · no-answer fixture abstains · throttling and 429 → fallback (respx) · `llm`-marked integration test against Ollama/Groq with the poisoned document, asserting the answer doesn't follow the injected instruction (run nightly or manually, and record results).

**Done when:** `/query` returns a grounded answer with valid `[S#]` on the demo corpus using Ollama (or Groq), and abstains on an unanswerable question.

**Pitfalls:** small local models format citations poorly, so use few-shot examples and a strict parser. Keep context ≤ ~5k tokens for free-tier TPM limits. Gemini's OpenAI-compatible endpoint reports usage differently, so normalize it.

**Close-out:** add Groq/Gemini variable names to `agent.md` §11. Commit `feat(rag): LLM gateway, grounded generation, abstention and citation validation`.

---

### Session 29 — SSE streaming, evidence status & conflict detection

**Refs:** §8.2, §16.1, §21.3, §21.4, §23, §27.7.3, §27.7.6 · **Depends on:** 28

**Goal:** answers stream to the client with stage updates, with no DB transaction held open during generation, ending in an honest evidence status.

**Tasks**
- [ ] `POST /v1/knowledge-bases/{kb}/query/stream` (SSE) emitting:
  - `meta` (query_run_id, trace_id, safe profile/model info)
  - `stage` (retrieval.started/completed with counts, rerank.started/completed, generation.started)
  - `sources` (alias metadata)
  - `answer_delta` (buffered to sentence/block boundaries or 50–100 ms batches, never per character)
  - `citation` (validated updates/corrections)
  - `done` (usage, abstained, evidence_status, conflicts, timing)
  - `error` (safe code + message)
- [ ] **Transaction discipline:** retrieval + context materialization in one transaction → **commit and close** → stream from the LLM → a new short transaction persists the answer, citations and timings.
- [ ] Incremental citation checking while streaming plus a final validation pass. Invalid aliases → `citation` correction events. Wholly invalid output → `error`/abstain event.
- [ ] Cancellation: client disconnect cancels the provider request and marks the run `cancelled`.
- [ ] Evidence status rules (written in `docs/evaluation/evidence-status.md`): **strong**, **partial**, **conflicting**, **insufficient**, **source unavailable**, **retrieval degraded**, all computed from explicit criteria, never from model "confidence".
- [ ] Conflict detection: selected evidence from different documents/versions covering the same topic with different effective dates or differing numbers → the prompt asks the model to describe the conflict, and `done.conflicts` lists both sources with version/effective date (§21.4).
- [ ] Keep-alive comments and headers `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

**Tests:** SSE event-order contract test (FakeLLM) · disconnect cancels · instrumentation proves no open DB transaction during streaming · evidence-status unit tests · the 2025-vs-2026 handbook fixture reports a conflict.

**Done when:** `curl -N` shows ordered events with a real model, and the leave-policy comparison reports the conflict.

**Close-out:** commit `feat(rag): SSE answer streaming, evidence status and conflict detection`.

---

### Session 30 — Ask workspace UI (FE-4 part 1)

**Refs:** §27.7.1–27.7.4, §27.7.6, §27.20, §27.24, §27.26 (streaming state), §28.2 (web safety) · **Depends on:** 25, 29

**Goal:** the core Ask experience: a composer with explicit scope, honest stage updates, and document-style streamed answers with live citations.

**Tasks**
- [ ] `/[org]/ask` empty state: compact title "Ask your organization", composer, visible scope, recent investigations, 3–5 example tasks derived **deterministically** from the user's KB names/descriptions (no LLM).
- [ ] Composer: multiline (Enter submits, Shift+Enter newline; or Cmd/Ctrl+Enter mode). Scope control: Company knowledge / Selected KBs / Selected documents / Model-only (only if policy permits), each with a privacy/retrieval explanation **before** submit. Attach (choose documents).
- [ ] SSE client: fetch-based reader sending the `Authorization` header (`@microsoft/fetch-event-source` or custom), aborted on cancel.
- [ ] **Answer-stream reducer/state machine** as a pure TS module with the §27.26 events (`query.accepted` … `query.cancelled`). No ad-hoc `isLoading`/`isStreaming` booleans.
- [ ] Stage line: collapses for fast answers (< ~800 ms); shows elapsed time and a cancel button for slow ones.
- [ ] Answer renderer: document typography (Source Serif for long answers) · `react-markdown` + `remark-gfm` + `rehype-sanitize` (strict schema, no raw HTML, links limited to http/https with `rel="noopener noreferrer"`) · completed blocks memoized so only the last block re-renders · tables appear as stable blocks · reserved space prevents layout jumps.
- [ ] Inline citations become interactive chips once `sources` arrives. Validator corrections update in place.
- [ ] Metadata row (scope · N sources searched · time) and actions: Sources, Feedback (Save/Export come with Projects in Session 36).
- [ ] Live region announces major state changes only, never streamed tokens (§27.24).
- [ ] E2E mode: `LLM_PROVIDER=fake` makes CI deterministic.

**Tests:** reducer covers every event sequence including error and cancel · sanitizer (`javascript:` links, `onerror` attributes, raw HTML stripped) · citation parser · Playwright: ask → streamed answer with citations.

**Done when:** Ask works end to end in the browser with streaming and citations.

**Close-out:** commit `feat(web): ask workspace with streaming answers and inline citations (FE-4a)`.

---

### Session 31 — Evidence rail, source viewer & feedback (FE-4 part 2) → **G5**

**Refs:** §7.9 (`feedback`), §26.2 (feedback), §27.7.5, §27.7.7, §27.10, §27.20.3, §27.21, §27.22, §27.30 (FE-4 exit) · **Depends on:** 30

**Goal:** every citation reaches its exact source passage in at most two interactions, and every answer state (abstain, conflict, degraded) is clear.

**Tasks**
- [ ] Evidence rail: clicking `[S4]` highlights the marker, opens/updates the rail with a `layoutId` transition (chip → rail header), and shows title, verified/authority state, source system, page/section, the exact passage with a short non-looping highlight, a surrounding-context toggle, permitted metadata, **Open document**, **Use only this source**, and **Report citation problem**. Answer scroll position is preserved. `[`/`]` move between citations when the rail is focused. `Esc` closes.
- [ ] Citation hover preview on desktop after a delay (none on touch).
- [ ] Source viewer: `react-pdf` (lazy) opens at the cited page and highlights the chunk's bbox (fallback: text-layer search). Non-PDF viewer renders DOCX/MD/HTML/PPTX/XLSX from canonical blocks with anchors (block id / slide / row range). Deep links `?doc=…&page=…&chunk=…`.
- [ ] Endpoints: `GET /v1/documents/{id}/versions/{vid}/content-url` (authorized, short-lived signed URL to the trusted original) · `GET /v1/chunks/{id}/context` (neighbors, authorized).
- [ ] Feedback: thumbs up/down + reason codes + optional comment → `POST /v1/query-runs/{id}/feedback`.
- [ ] States: abstention (§21.2: broaden scope, remove filters, search instead, inspect sources, ask an admin) · conflict card with side-by-side compare (§27.7.7) · degraded banner · source unavailable.
- [ ] Copy answer: plain text / Markdown / with citations / selected section.
- [ ] Gate script `tests/integration/test_gate_g5.py`: every successful answer has ≥ 1 valid alias (FakeLLM in CI; real-model nightly run recorded) · the no-answer fixture abstains · the poisoned fixture does not override policy (real model, result recorded in `agent.md`).

**Tests:** Playwright journey "login → Ask → citation → source page" for **PDF and DOCX** (**Demo 4**) · keyboard-only citation navigation · feedback persisted.

**Done when** — **G5 checklist:** valid aliases on every successful answer · abstention on no-answer · poisoned fixture contained · citation → source works for PDF + one non-PDF type. **The MVP core is complete.**

**Close-out:** mark G5. Commit `feat(web): evidence rail, source viewer, feedback and answer states (FE-4b)`. Tag `gate-G5`.

---

## Sprint 6 — Early MVP deployment (subset of plan Phase 14) → M1

### Session 32 — Free-tier accounts & deployable backend image

**Refs:** §38.2, ADR-008, `agent.md` D-002/D-003/D-006, I-001 · **Depends on:** 31

**Goal:** a single backend container that runs the whole backend and works against real free-tier services, proven locally before any deploy.

**Tasks**
- [ ] **Re-verify free tiers** (HF Spaces CPU Basic, Neon, Backblaze B2, Auth0, Vercel Hobby, Groq, Gemini) and write `docs/runbooks/free-tier-limits.md` with today's date and links. Update I-001.
- [ ] Create the free accounts (no card): Hugging Face, Neon, Backblaze B2, Auth0, Vercel (Groq and Gemini already exist from Session 28).
- [ ] `infra/docker/space.Dockerfile` (built FROM the backend image):
  - adds `redis-server`, `clamav` + `clamav-daemon` (freshclam at start), `supervisor`
  - `infra/docker/space/supervisord.conf` runs: uvicorn API on **port 7860**, Celery worker `ingestion` (concurrency 1), Celery worker `default,maintenance,llm`, dispatcher, beat, redis, clamd
  - runs as **uid 1000** (HF requirement); healthcheck
  - **bakes model weights** (Qwen3 embedding, reranker ONNX, Docling models) into image layers to avoid re-downloading on every cold start (free Spaces have no persistent disk)
  - entrypoint: wait for DB → `alembic upgrade head` (**staging only**; production migrations become a separate CD step in Session 61) → `supervisord`
- [ ] **Neon:** project `knowledgeos` with branches `main` (production later) and `staging`. Create roles by SQL (not the console, because console-created roles get elevated privileges): owner, `knowledgeos_app` (`LOGIN NOBYPASSRLS`), `knowledgeos_dispatcher`. Enable `vector` and `pg_trgm`. Require SSL. Use the **direct** connection string for asyncpg, or the pooled one with `statement_cache_size=0`.
- [ ] **Backblaze B2:** private buckets `kos-staging-{quarantine,trusted,artifacts}`, an application key scoped to them, S3-API CORS allowing `PUT`/`GET` from the Vercel staging domain and `localhost:3000`, and a quarantine lifecycle rule. S3 endpoint `https://s3.<region>.backblazeb2.com`.
- [ ] **Auth0:** a Regular Web Application for Auth.js (callback = Vercel staging URL), an API whose identifier = `OIDC_AUDIENCE`, refresh-token rotation, staging demo users. The app does authorization itself, so Auth0 RBAC stays off.
- [ ] `staging` settings profile: CORS allowlist, secure cookies, `require_malware_scan=true`, content logging off, generation Groq → Gemini, embeddings/reranker local.
- [ ] `make space-smoke`: run the Space image **locally** against Neon `staging` + B2 + Auth0, upload a file → `READY`, query via Groq.

**Done when:** the all-in-one image works locally against the real free-tier services.

**Pitfalls:** the Space must be **public** for the browser to reach it (private Spaces need an HF token on every request). The app's own auth protects data, and secrets go in **Space secrets**, never in the repo. Neon scales to zero, so allow a few seconds of cold start in readiness timeouts. Keep an eye on image size.

**Close-out:** add all new env var names to `agent.md` §11. Commit `feat(deploy): all-in-one backend image and free-tier staging configuration`.

---

### Session 33 — MVP staging deployment → **M1**

**Refs:** §37.2 (subset), §38.2, ADR-008 · **Depends on:** 32

**Goal:** a live, public staging demo of the core product on the $0 stack, deployed by a workflow.

**Tasks**
- [ ] HF Space `knowledgeos-api-staging` (Docker SDK). Space `README.md` front matter: `sdk: docker`, `app_port: 7860`.
- [ ] Vercel project for `apps/web` (root directory `apps/web`) with env vars (`AUTH_*`, Auth0 issuer/client, public API base URL). Its production deployment acts as "staging" for now; a separate production project comes in Session 61.
- [ ] `.github/workflows/deploy-staging.yml` (on push to `main` after CI, plus manual dispatch):
  - build and push the Space image to **GHCR** tagged with the git SHA
  - update the Space repository (its Dockerfile references `ghcr.io/<owner>/knowledgeos-space:<sha>`) using `huggingface_hub`; set secrets from GitHub secrets via `add_space_secret`
  - poll the Space runtime until it is `RUNNING`
  - run `scripts/smoke.py`: health, OIDC discovery, token for a dedicated smoke-test user (Auth0 password grant enabled for **staging only**), upload, search, query with citations
- [ ] Seed the staging demo org with `scripts/seed_demo.py --env staging`. Map Auth0 demo users to memberships by email on first login.
- [ ] Playwright smoke suite against the staging URL: login, search `HR-142-B`, ask with a citation.
- [ ] Optional keep-warm: a daily scheduled ping so the Space doesn't hit the 48 h sleep. Keep it light and within the terms of service.
- [ ] Update `agent.md` §4.8 with deploy steps and URLs. Add a "Live demo (staging)" link to the README.

**Done when** — **M1:** on the public staging URL a user can sign in → upload → reach `READY` → search → ask and get cited answers, and the deploy workflow is green.

**Close-out:** mark M1. Commit `ci(deploy): staging deployment workflow and MVP demo`. Tag `milestone-M1`.

---

## Sprint 7 — Conversations, routing, projects & compare (plan Phase 6, FE-5) → G6

### Session 34 — Conversations, history-aware rewrite & query router

**Refs:** §7.8 (`conversations`, `messages`), §16.3, §16.4, §24, §26.2 (Conversations) · **Depends on:** 29

**Goal:** multi-turn conversations whose follow-ups are rewritten safely, re-authorized each turn, and routed by query type.

**Tasks**
- [ ] Migration: `conversations`, `messages` (content stored per retention policy, `retention_expires_at`), `query_runs.conversation_id`, RLS.
- [ ] API: `GET/POST /v1/conversations`, `GET/DELETE /v1/conversations/{id}`. Query endpoints accept `conversation_id`. User and assistant messages are persisted (assistant linked to `answers`).
- [ ] History-aware rewrite (§16.4): rewrite **only** when the message has references ("that policy", "what about last year?", pronouns, very short follow-ups). Deterministic trigger + an optional small/fast free-model rewrite over a bounded window (last N turns or a summary).
  - The rewrite cannot add filters or widen scope (validated). On failure, use the original query. Store original + rewritten in the run/trace.
- [ ] Prior assistant answers are **never** evidence (§24). Only freshly retrieved chunks are.
- [ ] Access is re-checked on **every** turn with current principals.
- [ ] Query-type router `app/rag/planning/router.py` (§16.3): deterministic rules first (comparison verbs/"between X and Y" → `comparison`; "summarize/summary of" + document scope → `document_summary`; title/identifier match → `document_navigation`; "list all/how many/every" → `unsupported_exhaustive_or_aggregate`; else `fact_lookup` or `broad_topic`). Optional LLM classifier behind a flag. Store `query_type` on the run.

**Tests:** rewrite triggers (table-driven) · fallback on rewrite failure · no invented filters · **permission change between turns:** remove Hana from the HR group after turn 1 → turn 2 cannot use restricted evidence · router table tests.

**Done when:** "What is the parental leave policy?" followed by "What about in 2025?" resolves correctly in the demo.

**Close-out:** commit `feat(rag): conversations, history-aware rewrite and query router`.

---

### Session 35 — Comparison, document summary & guarded query paths

**Refs:** §1.2 (scenarios), §16.3, §17 · **Depends on:** 34

**Goal:** each query type gets the behaviour plan §16.3 requires, with no shortcuts around authorization.

**Tasks**
- [ ] **Comparison:** decompose into 2–4 bounded subqueries (deterministic split on "between X and Y", "vs", years, plus validated LLM-assisted decomposition) → retrieve evidence per side, each with the full authorization predicate → per-side context budget → `comparison/v1` prompt producing a structured comparison with citations per side, mentioning conflicts.
- [ ] **Document summary:** requires a resolved document scope (selected, or resolved through navigation with confirmation) → hierarchical map-reduce over that document's chunks within budget (section summaries → overall) with section-level citations. No caching in v1 (§30).
- [ ] **Navigation:** strong title/identifier boost; return document links first, then a short answer.
- [ ] **Exhaustive/aggregate:** answer from structured metadata (document listing with filters) or say explicitly that retrieval is not exhaustive, with a link to filtered Search.
- [ ] **Broad topic:** larger candidate pool with per-document diversity.
- [ ] Inferred-filter relaxation once (non-security only), traced.

**Tests:** "How did the leave policy change between 2025 and 2026?" cites both versions · a 30-page summary stays within the token budget · an exhaustive query returns the listing/disclaimer · property test: relaxation never touches authorization filters.

**Done when:** all six query types behave per §16.3 on the demo corpus.

**Close-out:** commit `feat(rag): comparison, document summary and guarded query paths`.

---

### Session 36 — Conversation UI & research Projects (FE-5 part 1)

**Refs:** §27.4 (Workspaces), §27.7.2, §27.11, §27.21 · **Depends on:** 31, 34

**Goal:** conversations are first-class, and research work persists in Projects rather than living only in chat history.

**Tasks**
- [ ] Ask threads: conversation list, lightweight follow-up prompts, document-style answers, title/save investigation, delete, retention notice.
- [ ] Projects backend. This **extends plan §7**; record it in `agent.md` §10.
  - Tables: `projects` (name, description, scope KB/document ids, created_by), `project_items` (type `conversation|saved_search|comparison|note`, ref id), `pinned_evidence` (chunk id, document version id, note, alias snapshot), `notes` (sanitized Markdown). All with RLS.
  - CRUD APIs. Pinned evidence is **re-authorized on every read**: if access was lost, it shows as unavailable without content.
- [ ] Projects UI: the dossier overview from §27.11 (Context, Work, Pinned evidence, Recent activity). Create a project from Ask/Search. Pin from the evidence rail. Text-selection contextual menu: Ask about selection, Pin evidence, Copy with citation, Open in source.
- [ ] Project activity feed.

**Tests:** pinned evidence becomes unavailable after permission revocation · Playwright: create project → pin a citation → reopen the project.

**Done when:** a user can collect conversations, evidence and notes in a project and return to them later.

**Close-out:** commit `feat: conversation threads and research projects (FE-5a)`.

---

### Session 37 — Compare / Matrix view (FE-5 part 2) → **G6**

**Refs:** §27.12, §27.20.5, §27.30 (FE-5 exit) · **Depends on:** 35, 36

**Goal:** a bounded, non-chat way to analyse many documents side by side, with every cell cited.

**Tasks**
- [ ] Backend: `comparison_runs` (2–50 document ids, up to ~8 column questions, status, optional project), `comparison_cells` (document, column, status, short answer, citations, error).
  - `POST` creates the run and enqueues **one Celery job per cell** on the `llm` queue (concurrency limited to respect free-tier RPM).
  - Each cell is a RAG query **scoped to that single document**.
  - `GET` the run, retry a failed cell, cancel the run.
- [ ] UI: pick documents (library/search/project) → define columns → matrix (rows = documents, columns = questions). Cells resolve in place (fade), failed cells retry independently, a cell expands into the evidence rail, sorting uses `layout` animation (with a row threshold), client-side CSV export.

**Tests:** cell idempotency · a cell never cites another document · Playwright: 3 documents × 2 questions with FakeLLM.

**Done when** — **G6 checklist:** follow-ups stay grounded (S34) · a permission change between turns is respected (S34) · projects and compare make cross-document work independent of chat history.

**Close-out:** mark G6. Commit `feat: bounded compare/matrix view (FE-5b)`. Tag `gate-G6`.

---

## Sprint 8 — Evaluation platform (plan Phase 7, FE-7) → G7

### Session 38 — Evaluation schema, runner & retrieval metrics

**Refs:** §7.9 (`eval_*`), §32.1, §32.3, §32.7, §32.8, §33 · **Depends on:** 31

**Goal:** a reproducible evaluation harness with deterministic retrieval metrics.

**Tasks**
- [ ] Dataset format `evals/datasets/<name>/v<N>/cases.jsonl` + `manifest.yaml` (version, corpus fixture reference, reviewers, content hash). Case schema = §32.1 as Pydantic (`evals/schema.py`).
  - Relevance is labelled by **document key + optional evidence quotes**, not chunk ids, because chunk ids change between index generations.
- [ ] Fixture loader: builds eval orgs/KBs/users/documents deterministically from `evals/fixtures/corpus/` and ingests them through the **real pipeline**. Cached by corpus hash + generation config.
- [ ] Tables `eval_datasets`, `eval_cases`, `eval_runs`, `eval_results` recording dataset version, git SHA, RAG profile version, index generation, model versions and metric versions.
- [ ] Runner CLI: `uv run python -m evals.run --dataset core --version 1 --profile default-hybrid-v1 [--retrieval-only] [--limit N]`. It runs every case **as the case's principal** through the real authorization path and writes `evals/experiments/<run_id>/report.{json,md}`.
- [ ] Deterministic metrics `app/rag/evaluation/metrics/retrieval.py`: Recall@K, Precision@K, HitRate@K, MRR, nDCG@K, relevant-document recall, duplicate rate, **authorized-violation count** (each hit re-checked against ACLs independently).
- [ ] Makefile: `eval-retrieval`, `eval-full`, `eval-smoke`.

**Tests:** metric unit tests against hand-computed examples · runner on 5 sample cases.

**Done when:** `make eval-retrieval` runs and produces a report.

**Close-out:** fill `agent.md` §4.7. Commit `feat(eval): evaluation schema, runner and retrieval metrics`.

---

### Session 39 — Evaluation corpus & golden set, part 1 (~100 cases)

**Refs:** §1.2, §32.1, §32.2, §32.8 · **Depends on:** 38

**Goal:** a realistic evaluation corpus and the first 100 **human-reviewed** golden cases.

**Tasks**
- [ ] Expand the synthetic eval corpus to ~40–80 original documents: HR, Support, Engineering, Compliance, non-English documents, 2025/2026 versions, restricted documents, near-duplicates across two orgs, and poisoned documents (injection, hidden Unicode, fake system messages).
- [ ] `evals/scripts/generate_candidates.py`: a free LLM (Groq/Gemini/Ollama) proposes question / expected answer / evidence-quote candidates per document and category into `candidates.jsonl`. **Candidates never go straight into the golden set.**
- [ ] `evals/scripts/review.py`: a terminal review tool to accept/edit/reject candidates, recording reviewer and notes.
- [ ] Write `docs/evaluation/golden-set-guidelines.md`: what makes a good case, answerability labels, quote rules.
- [ ] Review ~100 cases: 50 straightforward factual, 30 exact identifier/policy code, 20 paraphrased semantic.

**Done when:** 100 reviewed cases are committed with a manifest, and retrieval metrics run on them.

**Close-out:** commit `feat(eval): evaluation corpus and first 100 reviewed golden cases`.

---

### Session 40 — Golden set, part 2 (200 cases, frozen v1)

**Refs:** §32.2, §32.6, §39.4 · **Depends on:** 39

**Goal:** the complete, balanced, reviewed 200-case dataset from plan §32.2.

**Tasks**
- [ ] Add the remaining categories: +10 paraphrased (30 total), 20 cross-document comparisons, 20 unanswerable/abstention, 20 authorization/tenant-isolation (expected `access_denied` or no evidence for Bob/Carol fixtures), 15 multilingual/cross-lingual, 15 adversarial/prompt-injection/poisoning.
- [ ] Second review pass over all 200 for ambiguity, labels and quotes. Working solo, review again after a 24 h gap and record that in the manifest.
- [ ] Tag 20–30 high-signal, deterministic cases `smoke: true`.
- [ ] Freeze dataset **v1** (content hash in the manifest).
- [ ] `evals/scripts/check_distribution.py` verifies the category counts.

**Done when:** 200 reviewed cases, verified category counts, smoke subset tagged, v1 frozen.

**Close-out:** commit `feat(eval): complete 200-case golden dataset v1`.

---

### Session 41 — Generation & citation metrics, security gates, calibration & CI smoke eval

**Refs:** §2.2, §19, §32.4–32.8, §33, §37.1 · **Depends on:** 40

**Goal:** every quality and security dimension is measurable, thresholds are calibrated, and RAG changes are checked automatically on pull requests.

**Tasks**
- [ ] Generation metrics:
  - Ragas faithfulness, answer relevancy, context precision/recall, configured with a **free judge LLM** through an OpenAI-compatible base URL and the local embedding model
  - citation validity (deterministic)
  - citation support/precision and contradiction handling (judge with versioned rubrics in `evals/rubrics/`)
  - citation completeness
  - abstention accuracy (deterministic from answerability labels)
  - factual correctness against expected facts (judge + keyword checks)
- [ ] Judge cache keyed by `(case, answer hash, judge model, rubric version)` so runs resume after rate limits.
- [ ] **Security hard gates** (§32.6): cross-tenant leakage = 0 · unauthorized chunk selection = 0 · revoked document still searchable = 0 (the runner revokes, then queries) · poisoned override successes = 0. "Deleted document searchable = 0" activates in Session 49 and "local-only external calls = 0" in Session 54.
- [ ] Abstention calibration: sweep the rerank threshold over answerable vs unanswerable subsets, pick the threshold that maximises abstention accuracy while keeping a recall floor, save it as a **new RAG profile version**, and document it in `docs/evaluation/calibration.md`.
- [ ] Experiment runner: profile A vs profile B → report with aggregate deltas, **per-case regressions**, category breakdown, latency and estimated cost.
- [ ] CI `eval-smoke` job on PRs touching `app/rag/**`, `configs/prompts/**` or `configs/rag_profiles/**`: start the Compose stack, ingest the smoke corpus with the real local embedding model (HF cache via `actions/cache`), run the smoke cases with retrieval + deterministic metrics. Use generation through Groq if the secret exists, otherwise FakeLLM (LLM metrics skipped). Fail on any security-gate violation or a regression beyond threshold vs the stored baseline.
- [ ] Nightly workflow runs the full evaluation (when secrets exist) and uploads the report as an artifact.

**Done when:** a full run reports every metric for the default profile, the CI smoke eval is green, and calibration is recorded.

**Pitfalls:** free judge rate limits can make a full run take hours, so use concurrency 1–2 with caching. GitHub Actions jobs time out at 6 h.

**Close-out:** commit `feat(eval): generation and citation metrics, security gates, calibration and CI smoke eval`.

---

### Session 42 — Evaluation lab UI & gated profile promotion → **G7**

**Refs:** §26.2 (RAG configuration/evaluation), §27.14, §33, §27.30 (FE-7 exit) · **Depends on:** 41

**Goal:** administrators compare baseline vs candidate RAG profiles visually, and promotion is impossible when gates fail.

**Tasks**
- [ ] API:
  - `GET/POST /v1/knowledge-bases/{kb}/rag-profiles` (a candidate = base + validated overrides)
  - `POST /v1/rag-profiles/{id}/evaluate` (enqueue on the `eval` queue)
  - `POST /v1/rag-profiles/{id}/activate`: requires `evaluation.manage` + a passing run on the current dataset version + security gates passed + an explicit confirmation token. Audit `rag_profile.activated`.
  - `GET /v1/evaluations`, `GET /v1/evaluations/{run_id}`
- [ ] Live run status (polling or SSE).
- [ ] UI `/[org]/evaluate`: datasets, runs, baseline vs candidate (metric deltas in tabular numerals, latency, cost), a **REGRESSIONS** list, failure-taxonomy filters (retrieval miss, rerank miss, invalid citation, unsupported claim, wrong abstention, injection success, access violation), a side-by-side case inspector, and a promote button showing gate status. Restrained layout animation.
- [ ] Record the first official baseline in `docs/evaluation/baseline-v1.md` and in `agent.md`.

**Tests:** activation is blocked when a security gate fails (unit + API) · Playwright: open a comparison and inspect a regression.

**Done when** — **G7 checklist:** every profile change produces reproducible metrics · security failures block promotion (**Demo 10**, part 1).

**Close-out:** mark G7. Commit `feat: evaluation lab and gated RAG profile promotion (FE-7b)`. Tag `gate-G7`.

---

## Sprint 9 — Observability, feedback & cost (plan Phase 8, FE-8) → G8

### Session 43 — OpenTelemetry & Langfuse tracing

**Refs:** §3 (12, 13), §5.7, §31.1, §31.2 · **Depends on:** 31

**Goal:** every query and ingestion job produces a trace that explains the full retrieval path without leaking content.

**Tasks**
- [ ] `app/observability/tracing.py`: OTel SDK, resource attributes, OTLP exporter (local `grafana/otel-lgtm` in the `obs` Compose profile; Grafana Cloud OTLP endpoint in staging/production), sampling config.
- [ ] Auto-instrumentation: FastAPI, SQLAlchemy/asyncpg, HTTPX, Redis, Celery. Propagate context API → outbox payload (`traceparent`, from Session 16) → worker.
- [ ] Custom spans with exactly the plan §31.1 names:
  - query: `auth`, `query.normalize`, `query.rewrite`, `query.embed`, `search.vector`, `search.lexical`, `search.fusion`, `search.rerank`, `context.pack`, `llm.generate`, `citation.validate`, `persist`
  - ingestion: `upload.verify`, `malware.scan`, `parse`, `normalize`, `security.scan`, `chunk`, `embed`, `index`, `verify`
  - safe attributes only (§31.2): hashed org id, KB id, generation, profile, provider/model, candidate counts, selected chunk ids, latency, tokens, estimated cost, degraded flags, error codes. **No raw text.**
- [ ] `trace_id` stored on `query_runs` and `ingestion_jobs`, sent in SSE `meta`, and shown as a copyable ID in the UI.
- [ ] Langfuse (`app/observability/langfuse.py`): one trace per query with retrieval spans (chunk ids, scores), a generation observation (model, usage, latency) and scores from feedback. Prompt/answer **content is sent only if the org setting `trace_content` is true** (default false; otherwise hashes). Langfuse Cloud Hobby in staging/production.
- [ ] `trace_id`/`span_id` added to structlog output.

**Tests:** span-name/attribute contract test with an in-memory exporter · no content in spans when `trace_content=false` · API → worker propagation test.

**Done when:** one local query shows a complete span tree in Grafana/Tempo and a Langfuse trace with retrieval details.

**Close-out:** commit `feat(obs): OpenTelemetry instrumentation and Langfuse RAG traces`.

---

### Session 44 — Service metrics, dashboards & alerts

**Refs:** §26.2 (`/metrics`), §31.3, §31.4 · **Depends on:** 43

**Goal:** the operational health of the system is visible on dashboards and alerts fire on the plan §31.4 conditions.

**Tasks**
- [ ] Metrics (prometheus-client and/or OTel metrics): HTTP request/latency histograms by **route template**, retrieval/rerank/LLM latency, ingestion throughput and failures by stage, queue depth and oldest job age (gauge from PostgreSQL), connector sync success/failure, vector/lexical result counts, abstention rate, feedback ratio, rate-limit events, tokens/cost by provider/model/hashed org, DB pool saturation, Redis availability, object-store errors, authorization-denied count.
- [ ] `/metrics` protected (private network locally; bearer token on the public Space). On the free deployment, push metrics to Grafana Cloud through OTLP.
- [ ] `obs` profile scrapes API and workers locally.
- [ ] Dashboards as code `infra/monitoring/dashboards/*.json`: API, RAG quality/latency, ingestion & queues, providers & cost, security signals.
- [ ] Alert rules `infra/monitoring/alerts/*.yaml` for every §31.4 item (API error spike, old queue backlog, ingestion failure spike, DB unavailable/saturated, provider error spike, repeated source-sync failure, evaluation security regression, authorization-denied spike, cost threshold). Grafana Cloud free alerting → email.

**Tests:** expected metric names are exposed (unit) · alert rules validate (`promtool check rules` in CI via Docker).

**Done when:** dashboards show live local data, and alert rules validate in CI.

**Close-out:** commit `feat(obs): service metrics, dashboards and alert rules`.

---

### Session 45 — Usage ledger, budgets, rate limits & quotas

**Refs:** §26.2 (`/usage`), §28.2 (rate/abuse limits), §35, `agent.md` DV-004 · **Depends on:** 28

**Goal:** every model call is accounted for, abuse is throttled, and free-tier quotas degrade gracefully instead of failing randomly.

**Tasks**
- [ ] `usage_events` (org, KB, user/service account, provider, model, operation `generate|embed|rerank|judge`, input/output tokens, units, latency, `pricing_version`, `estimated_cost` at list price, `is_free_tier`, created_at). Written by the gateway and providers (local providers record tokens with zero real cost).
- [ ] `configs/pricing/pricing_v1.yaml`: versioned, date-stamped illustrative list prices.
- [ ] Controls:
  - org monthly **soft budget** (status-center warning) and optional **hard budget** (blocks generation with a clear error; search keeps working)
  - per-user query rate limit and per-org aggregate rate (Redis sliding window/token bucket)
  - per-org generation concurrency limit (Redis semaphore)
  - max query length, max evidence tokens (profile), daily upload size/count, connector caps, retry caps
- [ ] Free-tier quota awareness: track daily requests per provider against configured RPD and switch early to the allowed fallback, or degrade to "sources only" with a banner ("Cloud generation quota reached; showing retrieved sources").
- [ ] 429 responses use the error envelope + `Retry-After`.
- [ ] `GET /v1/usage?group_by=provider|model|kb|user|day` (admin).

**Tests:** rate limiter (Redis integration) · budget enforcement · usage aggregation · quota-exhausted fallback path.

**Done when:** usage is queryable by provider/model/day, and limits are enforced with clear errors.

**Close-out:** commit `feat: usage ledger, budgets, rate limits and quotas`.

---

### Session 46 — Observe UI, Home workspace & feedback review (FE-8) → **G8**

**Refs:** §27.6, §27.15, §27.20.3, §27.30 (FE-8 exit) · **Depends on:** 44, 45

**Goal:** administrators see system health and drill from any chart down to a single trace, and every user gets a useful Home.

**Tasks**
- [ ] Aggregate endpoints `GET /v1/observe/*` (from `query_runs`, `usage_events`, `ingestion_jobs`, `feedback`, connector runs).
- [ ] `/[org]/observe` (admin): summary strip (queries, P95 latency, error rate, abstention, feedback ratio, estimated spend, current generation, latest eval score) · trend charts (Recharts, lazy-loaded, with a table alternative for accessibility) for the §27.15 sections · **every chart links to a filtered table**, and every row links to the retrieval debugger for that trace.
- [ ] Feedback review: down-votes with reason/comment and a debugger link, "mark reviewed", and "create eval candidate" (feeds the Session 39 review tool), a light annotation queue.
- [ ] Home (§27.6): greeting, Ask field with a shared-layout transition into Ask, recent work, knowledge health (sources needing attention, failed jobs/syncs), recently updated knowledge, saved/verified collections, compact admin strip. No 12-card analytics grid.
- [ ] G8 drill, written up in `docs/runbooks/diagnose-bad-answer.md`: take a down-voted answer → query run → selected evidence → model response → OTel + Langfuse trace.

**Tests:** Playwright: Observe chart → table → debugger · Home renders correctly for member vs admin.

**Done when** — **G8 checklist:** a bad answer is traceable end to end · token/cost is visible · charts link to inspectable data.

**Close-out:** mark G8. Commit `feat(web): observe dashboards, home workspace and feedback review (FE-8)`. Tag `gate-G8`.

---

## Sprint 10 — Document lifecycle & zero-downtime reindexing (plan Phase 9) → G9

### Session 47 — Document version replacement & approval

**Refs:** §7.4, §9.3, §13.2, §21.1, §27.10, §41 (Demo 8) · **Depends on:** 31

**Goal:** replacing a document atomically switches retrieval to the new version, while history stays available.

**Tasks**
- [ ] End-to-end replacement: `POST /documents/{id}/versions` → upload → ingest into the active generation → on `READY` (and approval when required) **one transaction** sets `documents.active_version_id = new`, sets the old version's `effective_to = now()`, and emits a `document.version_activated` outbox event (cache-invalidation hook). The retrieval predicate already filters by active version, so old chunks disappear instantly but stay stored for history until retention GC.
- [ ] `effective_from`/`effective_to` captured from upload metadata or the approval form.
- [ ] Approval workflow polish: approval queue for knowledge managers, approve/reject with reason, audit.
- [ ] Version history API + UI: version list, read-only view of superseded versions, **split-pane block-level diff** (difflib on canonical blocks, aligned changed paragraphs), "restore previous version" (creates a new version from the old artifact and reindexes).
- [ ] `scripts/demo_version_replace.sh` (**Demo 8**).

**Tests:** after replacement, search returns only v2 chunks · v1 is still viewable in history · two concurrent replacements get unique version numbers and resolve deterministically.

**Done when:** Demo 8 works in the UI.

**Close-out:** commit `feat: document version replacement, approval and version diff`.

---

### Session 48 — Index-generation lifecycle: candidate, evaluate, activate, rollback

**Refs:** §7.6, §13.2, §25.2, §33 · **Depends on:** 42, 47

**Goal:** chunking or embedding changes are built side by side, evaluated, switched atomically and rolled back instantly, with zero downtime.

**Tasks**
- [ ] API (`kb.manage` + `evaluation.manage`): create a candidate generation (new embedding model / chunker config / parser pipeline), list generations, activate, roll back, retire.
- [ ] Candidate build: a resumable, concurrency-limited Celery bulk job that reprocesses every active document version **from canonical artifacts** (no re-parse unless the parser changed) → chunk → embed with the candidate's model → index into the candidate generation. Progress is tracked.
- [ ] **Dual-write:** documents ingested while a candidate is building go into **both** the active and the candidate generations.
- [ ] Promotion gate: the candidate needs a passing eval run (retrieval + security subset minimum), a passing security regression, and admin confirmation.
- [ ] Atomic switch: one transaction updates `knowledge_bases.active_index_generation_id` (and the paired RAG profile if any). The previous generation becomes `retired` but is retained for a configurable rollback window (e.g. 7 days). Query embedding always uses **the active generation's** model, resolved through the provider registry, so a mismatch is impossible.
- [ ] Instant rollback to the retained previous generation.
- [ ] GC task: batched deletion of chunks from retired generations past retention.
- [ ] Admin UI: generations list (status, model, chunker, created/activated), build progress, eval link, activate/rollback with confirmation.
- [ ] First real experiment: **bge-m3 vs Qwen3-Embedding-0.6B** as a candidate (plan §33) (**Demo 10**, part 2).

**Tests:** queries during the switch never mix generations · rollback works · dual-write during a build · GC removes only expired retired generations.

**Done when:** a candidate is built, evaluated, activated and rolled back in the local stack.

**Close-out:** commit `feat(rag): index-generation candidate build, activation and rollback`.

---

### Session 49 — Deletion cascade, retention & orphan sweeper → **G9**

**Refs:** §29, §30, §34.4, §39.4, §41 (Demo 9) · **Depends on:** 48

**Goal:** deleting content removes it from every derived system, with proof.

**Tasks**
- [ ] Deletion workflow (plan §29 steps 1–9):
  1. `DELETE` marks the document non-retrievable immediately and writes a `document.deleted` outbox event in the same transaction
  2. the worker deletes chunks from **all** generations (active, candidate, retired)
  3. invalidates canonical/derived artifacts per retention policy
  4. invalidates embedding-reuse candidates and any caches
  5. removes binaries once retention/legal hold allow (`retention_policies`: per org/KB retention days, legal-hold flag)
  6. keeps only a minimal audit tombstone
  7. runs a **verification job** (no chunk rows remain; a unique-phrase search returns nothing)
  8. stamps `deletion_verified_at` and logs completion
- [ ] KB archive/delete cascade and source deletion (reused by connectors in Session 50).
- [ ] Retention jobs: purge conversations/messages after `retention_expires_at`, redact stored query text/answers after N days per policy, expire feedback comments.
- [ ] Orphan sweeper (daily beat): chunks with missing/deleted versions, active-generation chunks from inactive versions past grace, upstream-deleted source objects still indexed (after Session 50), expired artifacts/uploads → fix + metric + report.
- [ ] Activate the eval security gate "deleted document searchable = 0".
- [ ] `scripts/demo_delete.sh` (**Demo 9**).

**Tests:** search returns nothing **immediately** after the DELETE call, before the worker runs · the verification job passes · legal hold blocks binary removal · the sweeper finds injected orphans.

**Done when** — **G9 checklist:** a replaced/retired document is not retrieved (S47) · deleted chunks cannot be found · generation rollback works (S48).

**Close-out:** mark G9. Commit `feat: deletion cascade, retention policies and orphan sweeper`. Tag `gate-G9`.

---

## Sprint 11 — Connectors & permission synchronization (plan Phase 10, FE-6 part 1) → G10

### Session 50 — Connector framework, sync engine & SSRF-safe web connector

**Refs:** §7.4 (`data_sources`, `source_objects`), §15, §15.1, §15.2, §15.3, §28.1 · **Depends on:** 49

**Goal:** a generic sync engine that detects new, changed, deleted, moved and re-permissioned objects, plus a web connector that cannot be abused for SSRF.

**Tasks**
- [ ] Connector protocol (§15) in `app/ingestion/connectors/base.py` + registry.
- [ ] `sync_runs` table (source, start/finish, status, counts new/changed/deleted/permission-changed, cursor before/after, safe error). APIs: `GET/POST /v1/knowledge-bases/{kb}/sources`, `POST /v1/sources/{id}/sync`, `GET /v1/sources/{id}/sync-runs`, `DELETE /v1/sources/{id}` (uses the Session 49 cascade).
- [ ] Sync engine:
  - `discover_changes(cursor)` → new/changed revision → fetch → new document version through the normal ingestion pipeline (`source_objects` maps external id → document)
  - deleted upstream → document deletion
  - **permission-only change** → update document ACL + `acl.changed` with no reprocessing
  - moved/renamed → metadata update
  - idempotent by `(source, external_id, external_revision)`
  - the cursor is acknowledged **only after** durable processing
- [ ] Scheduling via beat (per-source interval), manual sync, connector health status.
- [ ] Web/sitemap connector: config (start URLs or sitemap, allowed domains, max depth/pages, include/exclude patterns, robots policy). Revision = ETag / Last-Modified / content hash. Pages go through the Session 18 HTML path with canonical URL metadata.
- [ ] `app/security/safe_http.py` (used by **every** outbound fetch of user-supplied URLs):
  - scheme allowlist `http`/`https`
  - resolve DNS and reject if **any** address is loopback, private, link-local, multicast, reserved, CGNAT or cloud-metadata (`169.254.169.254`, `fd00::/8`, …), including IPv4-mapped IPv6 and decimal/octal/hex host forms
  - **connect to the validated IP** (pinned) while preserving Host/SNI, which defeats DNS rebinding
  - manual redirects (max 5) re-validated at every hop
  - response size cap, connect/read/total timeouts, content-type allowlist
  - URL canonicalization (strip fragments and tracking parameters), `robots.txt` (urllib.robotparser), per-domain rate limit

**Tests:** **SSRF suite**: localhost and every 127.0.0.1 encoding, `::1`, private ranges, metadata IP, redirect to a private address, DNS rebinding (resolver mock returns public then private), oversize response, non-HTTP schemes · sync diffing (new / changed / deleted / the same revision twice → no-op).

**Done when:** a web source syncs a small allowed site (a test server in Compose or a public docs site), and a re-sync detects changes and deletions.

**Close-out:** commit `feat(connectors): connector framework, sync engine and SSRF-safe web connector`.

---

### Session 51 — Google Drive connector & permission synchronization

**Refs:** §7.4, §15.1 (3), §15.2, §28.2 (Secrets) · **Depends on:** 50

**Goal:** a real enterprise-style connector whose source permissions control who can retrieve its content.

**Tasks**
- [ ] Google Cloud project (free, **no billing**) → enable the Drive API → OAuth consent screen in **testing** mode with test users → web OAuth client with the API callback URL.
- [ ] OAuth flow: creating a `google_drive` source returns an auth URL whose `state` carries a CSRF nonce bound to user + org → the callback exchanges the code → the **refresh token is encrypted** with envelope encryption (a per-secret data key wrapped by a master key from `KOS_MASTER_KEY` via AES-GCM/Fernet, behind a KMS-pluggable interface) and stored in `connector_secrets`. `data_sources.encrypted_config_ref` points to it. Scope: `drive.readonly`.
- [ ] Sync with the Changes API (`startPageToken` cursor), folder/shared-drive scope selection, Google Docs/Sheets/Slides exported to DOCX/XLSX/PPTX (or PDF), other files downloaded, revision from version/modifiedTime/md5.
- [ ] Permission sync: Drive permissions (users, groups, domain, anyone) → KnowledgeOS principals through an `external_identities` table (provider + external id/email → user or group). **Unmapped principals get no access (fail closed).** `anyone`/domain-wide map to the org principal only if org policy allows. Permission-only changes trigger ACL update + propagation (Session 23).
- [ ] API to map external groups/emails to KnowledgeOS groups/users.
- [ ] Token refresh and revocation handling (`invalid_grant` → source status `needs_reauth`).

**Tests:** fake Drive API (respx fixtures) for changes, permissions and export · mapping and fail-closed behaviour · removing a share updates chunk ACLs · the secret never appears in logs or responses.

**Done when:** a personal Drive test folder syncs, and removing a file's share removes access in KnowledgeOS after the next sync.

**Close-out:** add Google OAuth variable names to `agent.md` §11. Commit `feat(connectors): google drive connector with permission sync`.

---

### Session 52 — Sources UI & permission editor with propagation status (FE-6 part 1) → **G10**

**Refs:** §27.4 (Sources), §27.16, §27.22 (permission propagation), §27.23 · **Depends on:** 51

**Goal:** admins manage sources and permissions in the UI, and the UI never claims a permission change is live before the backend confirms it.

**Tasks**
- [ ] Sources UI per KB: list (type, status, last sync, counts, health) · add-source wizard (upload default; web: domains and limits; Drive: OAuth connect → folder picker) · sync now · sync-run history with actionable failures (needs re-auth, robots-blocked, SSRF-blocked domain, quota) · disable/delete with an impact preview ("N documents will be removed").
- [ ] Permission editor for KBs and documents:
  - inherited vs explicit access, with the origin explained ("via group HR", "via role member", "synced from Google Drive")
  - add/remove principals, with an **impact preview** before removal (counts of affected users computed under the admin's own authority; never shows content)
  - after save: "Updating searchable access…" until `acl_propagated_at` ≥ the change time → "✓ Search index confirmed at 14:32:09"
- [ ] External identity mapping UI (Drive groups/emails → KnowledgeOS users/groups).
- [ ] Sync failures appear in the status center.
- [ ] Gate script `tests/integration/test_gate_g10.py`: changed, deleted and re-permissioned source data propagates (web + fake Drive).

**Tests:** Playwright: remove Bob's access to a restricted document → propagation confirmed → Bob's search returns nothing (plan §27.29 journey 5).

**Done when** — **G10 checklist:** changed/deleted/re-permissioned source data propagates correctly, with backend-confirmed status in the UI.

**Close-out:** mark G10. Commit `feat(web): sources management and permission editor with propagation status (FE-6a)`. Tag `gate-G10`.

---

## Sprint 12 — Local/cloud model policy (plan Phase 11, FE-6 part 2) → G11

### Session 53 — Local model serving & policy-enforcing provider router

**Refs:** §7.7 (`model_policies`), §25.1, §25.2, §28.3, §34.3 · **Depends on:** 45

**Goal:** model policy is enforced in **one** backend chokepoint, so restricted content can never reach an external provider by accident.

**Tasks**
- [ ] Compose profile `local-models`: Ollama service (pull a small configurable model such as `qwen3:4b` or `llama3.2:3b`) and optionally TEI/Infinity as an out-of-process embedding/reranker alternative. In-process stays the default.
- [ ] Provider registry where every provider config declares `is_external` explicitly.
- [ ] `app/providers/router.py`, the **only** way application code obtains a provider: `get_llm(ctx, kb, purpose)`, `get_embedder(generation)`, `get_reranker(ctx, kb)`.
  - Checks the KB policy (cloud allowed / local preferred with cloud fallback / **local only**) separately for document embedding, query embedding, reranking and generation.
  - Checks the **max classification allowed for external providers** against the classification of every document in the packed context. If anything exceeds it, external generation is forbidden: use a local model or abstain with an explanation.
  - **Default deny** when no policy exists.
- [ ] Architectural guard: a test (import-linter contract or AST scan) fails if anything outside `app/providers/` imports a concrete provider class.
- [ ] Fallback rules from §25.2: generation falls back only to allowed compatible models · reranker may be bypassed if the profile permits · vector ↔ lexical-only if permitted and traced · **query embedding is never substituted** · authorization failure never degrades (fail closed).
- [ ] Circuit breaker per provider (open after N consecutive failures, half-open probe) + provider health metrics and an admin status endpoint.
- [ ] Egress accounting: every outbound provider call uses an instrumented httpx client incrementing `external_provider_requests_total{provider}`.

**Tests:** **Hypothesis policy matrix** over policy × classification × provider externality: an external provider is never chosen when forbidden · circuit-breaker states · import-guard test.

**Done when:** switching a KB to local-only routes generation to Ollama and embedding/rerank to local models, while a cloud-allowed KB uses Groq.

**Close-out:** commit `feat(providers): local model profile and policy-enforcing provider router`.

---

### Session 54 — Model-policy UI & zero-external-call proof → **G11**

**Refs:** §25.1, §27.18 (step 4), §32.6, §41 (Demo 11) · **Depends on:** 53

**Goal:** admins set privacy/model policy in plain language, and an automated test proves local-only really means local-only.

**Tasks**
- [ ] API: `GET/PUT` model policy per KB (`model_policy.manage`), audit `model_policy.changed`. Changing the embedding provider **requires a new index generation**; the API refuses a silent switch and the UI links to the Session 48 flow.
- [ ] UI (Settings → Privacy & models): modes with plain-language consequences, advanced per-operation overrides, max external classification, allowed fallbacks, live provider health. A "Local only" badge on the KB, visible in the Ask scope selector.
- [ ] Automated proof `tests/security/test_local_only_zero_egress.py`: create a local-only KB (local embedding generation) → ingest + query + rerank + generate with Ollama (FakeLocalLLM in CI) while the network is guarded (`pytest-socket` allowing only local/Compose hosts, plus respx strict mode) → assert `external_provider_requests_total` delta == 0. Also prove that with Groq configured as available, the router still **refuses** it for this KB.
- [ ] Activate the eval security gate "local-only external calls = 0".
- [ ] `scripts/demo_local_only.sh` (**Demo 11**) shows the counter staying at zero on Observe.

**Done when** — **G11 checklist:** a local-only KB produces **zero** external model-provider requests in an automated test.

**Close-out:** mark G11. Commit `feat: model privacy policy UI and zero-egress local-only proof`. Tag `gate-G11`.

---

## Sprint 13 — Security hardening (plan Phase 12, FE-6 part 3) → G12

### Session 55 — Threat model, scoped API keys & web security headers

**Refs:** §7.10, §26.1, §26.2 (Admin), §28, §28.1, §28.2 · **Depends on:** 54

**Goal:** the formal threat model exists, programmatic access works through scoped hashed API keys, and the web surface is locked down.

**Tasks**
- [ ] `docs/threat-model/THREAT_MODEL.md`: data-flow diagram, trust boundaries (browser, Vercel, API, workers, DB, object store, IdP, LLM providers, connectors), assets, STRIDE per component, **every §28.1 threat** with its controls and the tests that prove them, residual risk and owner.
- [ ] API keys:
  - create (secret shown **once**; format `kos_<prefix>_<secret>`; stored as a slow hash or HMAC-SHA256 with a server pepper), list, revoke, expiry
  - scopes (`search:read`, `query:execute`, `documents:write`, `audit:read`, …) mapped onto permissions
  - service-account principal token `apikey:<id>` usable in ACLs
  - auth dependency accepts a Bearer JWT **or** `X-API-Key`; constant-time comparison; throttled `last_used_at` writes; audit create/revoke
- [ ] API security headers: HSTS (production), `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`, strict CORS allowlist from config.
- [ ] Next.js security headers: nonce-based **CSP** (`script-src 'nonce-…'`, `connect-src` limited to API + Auth0 + B2, `object-src 'none'`, `frame-src 'none'`), Permissions-Policy, cookie flags (Secure, HttpOnly, SameSite=Lax). Auth.js provides CSRF protection on its routes. The API uses bearer tokens, not cookies, so CSRF doesn't apply there (document this).
- [ ] XSS audit: answer renderer, source viewer (HTML sources are rendered from canonical blocks, **never** raw source HTML), notes. Extend the sanitizer test corpus.
- [ ] Review connector-secret encryption and write a key-rotation procedure.

**Tests:** API-key auth and scopes · revoked/expired keys rejected · CSP header snapshot · XSS payload corpus against every renderer.

**Done when:** the threat model is complete, API keys work for `/search` and `/query` programmatically, and the headers are verified.

**Close-out:** commit `feat(security): threat model, scoped API keys and security headers`.

---

### Session 56 — Security regression suite, red-team set & supply-chain scanning

**Refs:** §5.8, §28.2, §31.4, §32.6, §37.1, §39.4 · **Depends on:** 55

**Goal:** every mandatory security case is an automated test, and dependencies and containers are scanned on every PR.

**Tasks**
- [ ] `tests/security/`: one module per mandatory case **SEC-01…SEC-15** (see Appendix D). Cases created in earlier sessions are consolidated here with the stable SEC ids.
- [ ] Red-team dataset `evals/datasets/redteam/v1`: injection variants, multilingual injections, encoded instructions, role-play, requests to reveal inaccessible documents. Run with a real model nightly; judge with string checks + rubric.
- [ ] Reconnaissance detection: per-user counters for authorization denials and zero-result probing of restricted-looking titles → alert + audit `security.recon_suspected`.
- [ ] CI security jobs: **Semgrep** (Python, TypeScript, OWASP rulesets), **pip-audit**, **pnpm audit** (production deps), **Trivy** (image + filesystem), **Syft** SBOM (SPDX) uploaded as an artifact, gitleaks (existing). Fail on high/critical, with a reviewed allowlist file for accepted false positives.
- [ ] Grafana security panel: authorization denials, injection flags, SSRF blocks, rate-limit hits.
- [ ] Triage and fix every finding. Record accepted risks in the threat model.

**Done when:** `make test-security` is green, the CI security jobs are green, and there is no open critical/high finding.

**Close-out:** commit `test(security): mandatory security regression suite, red-team set and supply-chain scanning`.

---

### Session 57 — Audit log UI, API key UI & onboarding flow (FE-6 part 3) → **G12**

**Refs:** §27.16, §27.17, §27.18, §27.30 (FE-6 exit) · **Depends on:** 56

**Goal:** security-relevant state is inspectable in the UI, and a new organization reaches value quickly.

**Tasks**
- [ ] `GET /v1/audit-events` (cursor pagination, filters, `audit.read`).
- [ ] Audit log UI: dense virtualized table (timestamp, actor, action, resource, outcome, request/trace id, IP/device if policy permits), filters, expandable structured details (monospace JSON), copy buttons, deep links to resources and debugger traces.
- [ ] API key UI: create (scope picker, expiry), secret shown once with copy, list (prefix, scopes, last used, expiry), revoke with confirmation.
- [ ] Onboarding (§27.18): create/join org → workspace name/use case → first library → **privacy/model policy choice explained** → upload bundled synthetic sample files or connect a source → live pipeline → automatic transition into the first Ask → a citation → source demonstration → *then* invite teammates. No 12-step wizard.
- [ ] Members/groups polish: last active, identity mappings.

**Tests:** Playwright onboarding journey for a brand-new user · audit entries appear for a permission change and an API-key creation.

**Done when** — **G12 checklist:** the security regression suite passes in CI (S56) · no unresolved critical/high · security-sensitive UI state is explicit and backend-confirmed.

**Close-out:** mark G12. Commit `feat(web): audit log, API key management and onboarding flow (FE-6b)`. Tag `gate-G12`.

---

## Sprint 14 — Performance & resilience (plan Phase 13) → G13

### Session 58 — Benchmark dataset & retrieval performance tuning

**Refs:** §8.4, §36.1, §36.3, `agent.md` DV-005, I-003 · **Depends on:** 57

**Goal:** measured retrieval performance at 100k+ chunks with multiple tenants and ACL patterns, and evidence-based tuning.

**Tasks**
- [ ] `scripts/bench/generate_corpus.py`: ~5 orgs, ACL patterns (org-wide, group-restricted, user-restricted), **100k+ chunks** (with a path to 250k/1M), templated synthetic text. Embeddings precomputed once with the local model and cached to Parquet (or random normalized vectors for pure-latency runs; document which). Bulk-load with `COPY` straight into `chunks`. Runs **locally**, not on Neon.
- [ ] `tests/load/bench_retrieval.py`: a query set with known relevant chunks; latency P50/P95/P99 per branch and fused; **filtered recall vs exact search** by org size and ACL selectivity.
- [ ] Tuning, each step measured and recorded:
  - HNSW `m`/`ef_construction` rebuilds, `ef_search`, iterative-scan mode and `max_scan_tuples`
  - **`halfvec(1024)`** storage experiment (size, recall, latency)
  - join-based predicate vs a denormalized `retrievable` flag
  - GIN `fastupdate`, `work_mem`, pool sizes, asyncpg statement cache, parallel branch execution
  - `EXPLAIN (ANALYZE, BUFFERS)` captured for the main queries
- [ ] Reranker CPU tuning: 20 vs 30 candidates, `max_length` 256/384/512, ONNX int8 vs fp32, thread count. Check the quality impact on the eval subset.
- [ ] `docs/benchmarks/retrieval.md` with hardware specs and every result. Apply the chosen settings through migrations/config.

**Done when:** documented numbers exist and the chosen settings are applied. Update I-003.

**Close-out:** commit `perf: benchmark corpus generator and retrieval tuning`.

---

### Session 59 — Load tests, chaos tests & benchmark report → **G13**

**Refs:** §34, §36.2, §39.5, §41 (Demo 12) · **Depends on:** 58

**Goal:** known behaviour under load and failure, written up honestly.

**Tasks**
- [ ] k6 (or Locust) scenarios in `tests/load/`:
  - search-only QPS ramp
  - full-RAG concurrency with FakeLLM (isolates infrastructure) + a small real-LLM run within free limits
  - simultaneous uploads
  - connector sync while users query
  - **permission updates during query load, with correctness assertions** (no unauthorized result ever appears under concurrency)
  - deletion and reindex under load
- [ ] Collect: latency percentiles, `pg_stat_statements`, pool saturation, Redis latency, HNSW behaviour, queue depth, CPU use of local models.
- [ ] Chaos tests in `tests/chaos/` (toxiproxy in Compose where useful): kill a worker mid-ingestion (from S20), Redis restart (Celery reconnects, outbox republishes), object-store timeout, LLM timeout → fallback, embedding timeout → retryable failure with no substitution, reranker timeout → degraded, transient DB failure → retries / fail closed, duplicate outbox delivery, connector returning the same revision twice.
- [ ] `docs/benchmarks/report.md`: methodology, hardware, results vs plan §2.2 targets, bottleneck analysis, **revised SLOs with evidence** where the $0 stack can't meet a target (e.g. CPU reranking), and scaling recommendations following §36.3.

**Done when** — **G13 checklist:** benchmark results and bottleneck analysis documented · SLOs met or explicitly revised with evidence.

**Close-out:** mark G13. Commit `test(perf): load and chaos test suites with benchmark report`. Tag `gate-G13`.

---

## Sprint 15 — Production CI/CD & deployment (plan Phase 14) → G14

### Session 60 — Production images, Terraform & secrets management

**Refs:** §28.2 (Secrets), §34.5, §37.3, §38.2, §38.3, I-001 · **Depends on:** 59

**Goal:** the production environment is described as code and can be recreated from the repository.

**Tasks**
- [ ] **Re-verify free-tier limits** and update `docs/runbooks/free-tier-limits.md` (I-001).
- [ ] Image hardening: base images pinned by digest, non-root, minimal packages, no build tools at runtime, HEALTHCHECK, worker/process counts tuned for 2 vCPU / 16 GB, baked model files checksummed, image-size budget, Trivy clean.
- [ ] `infra/terraform/free-stack/` (remote state in **HCP Terraform free**), workspaces `staging` and `production`:
  - Vercel (`vercel/vercel`): projects, env vars, domains
  - Neon (community provider): project and branches. Roles and extensions come from the idempotent SQL bootstrap script `infra/sql/neon_bootstrap.sql`
  - Backblaze B2 (`Backblaze/b2`): buckets, CORS, lifecycle, scoped keys (or Cloudflare R2 via `cloudflare/cloudflare`)
  - Auth0 (`auth0/auth0`): application, API, callbacks, connection
  - Grafana (`grafana/grafana`): dashboards, alert rules, contact points
- [ ] HF Spaces through `scripts/deploy/hf_space.py` (`huggingface_hub`: create the Docker Space, set secrets/variables), invoked by CD.
- [ ] `infra/terraform/aws-reference/` (plan §38.3 enterprise reference): ECS Fargate api/worker, RDS PostgreSQL + pgvector, ElastiCache, S3, KMS, Secrets Manager, ALB + WAF, private VPC subnets, CloudWatch. **`terraform validate` + `tflint` in CI only, never applied.** Its README says so.
- [ ] Secrets: never in the repo. GitHub Actions **environments** (`staging`, `production` with required reviewers), Space secrets, Vercel env vars. Write `docs/runbooks/rotate-secrets.md`.

**Done when:** `terraform plan` for staging shows the expected resources, a fresh staging environment can be recreated (Terraform + Space script + SQL bootstrap), and the AWS module validates.

**Close-out:** commit `feat(infra): hardened images, terraform for free stack and AWS reference module`.

---

### Session 61 — Full CD pipeline & release process

**Refs:** §32.7, §34.5, §37.2, §37.3 · **Depends on:** 60

**Goal:** every merged change flows automatically to staging, through quality and security gates, and to production with approval and automatic rollback.

**Tasks**
- [ ] `.github/workflows/deploy.yml`:
  1. on merge to `main`: build **immutable** images tagged with the git SHA (plus semver on release tags), push to GHCR with an SBOM attestation
  2. deploy staging (Space → SHA, Vercel staging)
  3. **migrations as a separate step** with the owner role (expand/migrate/contract; staging first)
  4. smoke tests
  5. security + RAG eval subset against staging (smoke dataset; FakeLLM if free quota is exhausted)
  6. **manual approval** (GitHub environment protection)
  7. production deploy (Neon `main`, production Space, production Vercel project), migrations (backward-compatible only)
  8. **post-deploy synthetic checks**: known-answer query with citation validation + tenant-isolation probe
  9. **automatic rollback** to the previous SHA on failure. Migrations are expand-only, so a code rollback is safe.
- [ ] Migration safety in CI: upgrade from the previous release's schema, plus a lint that blocks destructive operations (drop column/table) unless annotated `-- contract` and shipped in a separate release.
- [ ] Release versioning: semver tags (`v0.x` → `v1.0.0` in Session 65), changelog via release-please or git-cliff, GitHub Releases with SBOM and links to the eval/benchmark reports.
- [ ] Create the production Space `knowledgeos-api` and production Vercel project (through S60's Terraform/script). Not announced publicly until Session 62.
- [ ] Optional: a Neon branch per PR (free tier allows 10 branches).

**Done when:** a commit reaches staging automatically and production after approval, and a **rollback rehearsal** works (deploy a deliberately broken build → synthetic check fails → automatic rollback succeeds).

**Close-out:** commit `ci(cd): staged deployment pipeline with gates, migrations and rollback`.

---

### Session 62 — Production launch, backups, restore drill & runbooks → **G14**

**Refs:** §31.4, §34.5, §37.2, §38.2 · **Depends on:** 61

**Goal:** production is live, backed up, monitored and recoverable, and the recovery has been tested.

**Tasks**
- [ ] Production data: seed the demo organization(s) with the synthetic corpus. Auth0 production application. Reviewer demo accounts with tight quotas/budgets to protect free LLM quotas. Choose a signup policy (invite-only, or open with strict rate limits).
- [ ] Backups:
  - verify Neon free-tier point-in-time restore/history retention
  - **plus** a scheduled GitHub Actions `pg_dump` → encrypted with `age` → stored in B2 (within the 10 GB free tier) with retention
  - B2 object versioning/lifecycle for original documents
- [ ] **Restore drill:** restore the latest dump into a fresh Neon branch → run smoke tests against it → record RTO/RPO in `docs/runbooks/restore.md`. Document how to rebuild the vector index from canonical artifacts (reindex procedure).
- [ ] Runbooks in `docs/runbooks/`: deploy, rollback, restore, rotate secrets, incident response (provider outage, quota exhaustion, ingestion backlog), free-tier sleep/wake behaviour, onboarding a new org, handling a security report.
- [ ] Production observability: Grafana Cloud dashboards + email alerts, Langfuse production project with content tracing off, an uptime check (scheduled GitHub Action or a free uptime service).
- [ ] Run **Demos 1–12** (Appendix B) against production, or against staging for destructive ones, and record the results and screenshots.

**Done when** — **G14 checklist:** a fresh environment can be provisioned and deployed from the repository (S60–S61) · restore **and** rollback are documented and tested · production is live.

**Close-out:** mark G14. Fill `agent.md` §4.8. Commit `chore(release): production launch, backups and runbooks`. Tags `gate-G14`, `v0.9.0`.

---

## Sprint 16 — Polish & release evidence (plan Phase 15, FE-9, FE-10) → G15

### Session 63 — Public landing page (FE-9)

**Refs:** §27.19, §27.20.8, §27.20.9, §27.30 (FE-9) · **Depends on:** 62

**Goal:** a distinctive, honest public page that explains what KnowledgeOS does and proves the engineering depth.

**Tasks**
- [ ] Public route outside the app shell. Hero "From question to evidence" as the §27.19 split composition. The pipeline animation is deterministic and honest: labelled as an illustration, or driven by a recorded real trace.
- [ ] Sections 1–11 from §27.19: product preview, interactive citation transition, hybrid retrieval (exact + semantic merging), permission-aware architecture, ingestion lifecycle, retrieval debugger preview, evaluation before/after, local/cloud routing, architecture diagram (SVG), security/observability, GitHub/demo CTA.
- [ ] Motion: `whileInView`/`useScroll` used sparingly, full reduced-motion variants, never forced cinematic scrolling.
- [ ] SEO: metadata, Open Graph image, sitemap. Static rendering, optimized images, lazily loaded sections.
- [ ] Lighthouse + axe review.

**Done when:** Lighthouse mobile scores ≥ 90 for performance, accessibility, best practices and SEO (target), reduced-motion behaviour is complete, and the page makes no misleading claims.

**Close-out:** commit `feat(web): public landing page (FE-9)`.

---

### Session 64 — Frontend refinement (FE-10)

**Refs:** §27.24, §27.25, §27.29, §27.30 (FE-10), §27.31 · **Depends on:** 63

**Goal:** the whole frontend meets the plan's §27.31 definition of done.

**Tasks**
- [ ] Profile animation and performance: Ask composer input latency during streaming, source-viewer open latency, long tasks. Remove any animation that doesn't aid comprehension.
- [ ] Bundle analysis and splitting: admin, debugger, evaluation, observe and the PDF viewer stay out of the employee Ask bundle.
- [ ] Visual regression (Playwright screenshots, committed baselines): light/dark, normal/reduced-motion end states, empty/loading/error/populated, at 1440 / 1024 / mobile widths.
- [ ] Accessibility audit: axe on every route + manual keyboard pass + **NVDA** (free) screen-reader smoke test on Windows. Fix every critical issue.
- [ ] Copy and terminology cleanup (ordinary users never need RAG jargon). Density tuning with thousands of rows. Mobile task-flow testing.
- [ ] Web-vitals reporting (LCP, INP, CLS) into observability.

**Done when:** every item of the plan §27.31 frontend definition of done is true, with evidence linked in `agent.md`.

**Close-out:** commit `perf(web): frontend refinement, accessibility and visual regression (FE-10)`.

---

### Session 65 — Release evidence & v1.0.0 → **G15**

**Refs:** §40 (Phase 15), §41, §44, §45 · **Depends on:** 64

**Goal:** anyone can understand, run and evaluate KnowledgeOS from the repository alone, and v1.0.0 is released.

**Tasks**
- [ ] README quick start: clone → `make up` → `make seed` → log in, in ≤ 15 minutes. Test it on a clean machine/VM (or GitHub Codespaces free hours).
- [ ] Architecture diagrams (system; deployment: local / free-tier / enterprise reference) and an ER diagram generated from the models (Mermaid or `eralchemy`).
- [ ] API examples (curl + Python) for search and query with an API key.
- [ ] Reports: evaluation report (baseline vs final, per category), security report / threat-model summary, benchmark report (from S59).
- [ ] Design trade-offs document (ADR index + narrative) and a **measured limitations** statement (free-tier constraints, CPU reranking, no "enterprise-ready" exaggeration).
- [ ] Roadmap (post-v1: more connectors, OpenSearch/Qdrant backend through `SearchBackend`, agents still deferred).
- [ ] Demo video (OBS, free) covering Demos 1–12, plus screenshots.
- [ ] Final plan §44 checklist with an evidence link for every item (Appendix A).
- [ ] Release: tag `v1.0.0`, GitHub Release with changelog and SBOM.

**Done when** — **G15 checklist:** an outside reviewer (a friend or peer) runs the project from the README without help · every plan §44 item is checked with evidence · v1.0.0 is released.

**Close-out:** mark G15 and set `agent.md` status to "v1.0.0 released". Commit `docs(release): v1.0.0 release evidence`. Tags `v1.0.0`, `gate-G15`.

---

## Appendix A — Definition-of-Done traceability (plan §44)

| plan §44 item | Delivered in session(s) |
|---|---|
| **Product** | |
| Organization onboarding works | 09, 10, 57 |
| Multiple organizations are isolated | 08, 12 (RLS meta-test), 56 |
| Users/groups/roles work | 06, 09, 11 |
| KB-level and document-level access works | 12, 23, 52 |
| Core document formats ingest | 17, 18 |
| Scanned PDF/image OCR works | 18 |
| Web source and one cloud-document connector work | 50, 51 |
| Version replacement works | 47 |
| Deletion fully propagates | 49 |
| Chat/search UX works | 25, 30, 31, 36 |
| Citations open the exact source location | 31 |
| **RAG** | |
| Dense retrieval | 22, 24 |
| Lexical retrieval | 23, 24 |
| Hybrid fusion | 24 |
| Reranker | 27 |
| Context budgeting | 27 |
| Evidence-only prompt | 28 |
| Abstention | 28, 41 (calibration) |
| Citation validation | 28, 29 |
| Conversation rewrite implemented safely | 34 |
| Comparison/summary routing | 35 |
| Index generations: candidate/evaluate/activate/rollback | 22, 48 |
| **Security** | |
| OIDC validation | 07 |
| Tenant RLS | 08 |
| Chunk-level authorization metadata | 23 |
| Prompt-injection defenses | 19, 28, 56 |
| File quarantine/malware validation | 13, 14, 17 |
| SSRF protection | 50, 56 |
| XSS/unsafe-Markdown controls | 30, 55 |
| Rate limits | 45 |
| Scoped hashed API keys | 55 |
| Connector secrets encrypted | 51 |
| Local-only model policy enforcement | 53, 54 |
| Threat model documented | 55 |
| Security regression suite passes | 56 |
| **Evaluation** | |
| 200+ reviewed cases | 39, 40 |
| Retrieval metrics | 38 |
| Generation/grounding metrics | 41 |
| Citation metrics | 41 |
| Abstention metrics | 41 |
| Authorization/security hard gates | 41, 49, 54 |
| Baseline/candidate comparison | 41, 42 |
| PR smoke eval | 41 |
| Full pre-release eval | 41, 61, 65 |
| **Operations** | |
| Structured logs | 03 |
| Distributed traces | 43 |
| RAG traces | 43 |
| Cost/token analytics | 45, 46 |
| Queue/job dashboards | 44 |
| Alerts | 44, 62 |
| Backup/restore plan | 62 |
| Idempotent ingestion | 16, 20 |
| Transactional outbox | 16 |
| Load tests | 59 |
| Failure recovery tests | 20, 59 |
| Staging environment | 32, 33, 61 |
| Production/demo environment | 62 |
| CI/CD | 04, 33, 41, 56, 61 |
| Infrastructure as code | 60 |
| **Portfolio evidence** | |
| Architecture diagram | 04, 65 |
| ER/data model | 65 |
| Threat-model summary | 55, 65 |
| RAG evaluation report | 42, 65 |
| Performance benchmark report | 58, 59 |
| Demo video | 65 |
| Screenshots | 62, 65 |
| README quick start | 65 |
| Public API examples | 65 |
| ADRs describing major trade-offs | 04 (+ new ADRs whenever a major decision is made) |
| Clear statement of measured limitations | 59, 65 |

---

## Appendix B — Demo scenarios (plan §41)

| # | Demo | Built in | Verified in |
|---|---|---|---|
| 1 | Semantic retrieval (paraphrased question) | 24, 25 | 26 (gate script), 62 |
| 2 | Exact policy code `HR-142-B` | 23, 25 | 25 (Playwright), 62 |
| 3 | Reranking in the retrieval debugger | 26, 27 | 27, 62 |
| 4 | Citation `[S2]` opens the exact PDF page | 31 | 31 (Playwright), 62 |
| 5 | Access control (manager vs member) | 23, 25 | 25, 52, 62 |
| 6 | Tenant isolation (similar docs in two orgs) | 08, 25 | 25, 56, 62 |
| 7 | Prompt injection contained | 19, 28 | 31 (gate script), 56, 62 |
| 8 | Version replacement | 47 | 47, 62 |
| 9 | Delete propagation | 49 | 49, 62 |
| 10 | Evaluation of two profiles before activation | 42, 48 | 48, 62 |
| 11 | Local-only mode with zero external calls | 53, 54 | 54, 62 |
| 12 | Failure recovery (kill worker mid-job) | 20 | 20, 59, 62 |

---

## Appendix C — plan.md phase → session map

| plan.md phase | Sessions |
|---|---|
| Phase 0: Architecture & repository foundation | 01–05 |
| Phase 1: Authentication, organizations & authorization | 06–11 |
| Phase 2: Knowledge bases, uploads & object storage | 12–15 |
| Phase 3: Reliable ingestion engine | 16–21 |
| Phase 4: Indexing & retrieval-only search | 22–26 |
| Phase 5: Reranking, context & grounded generation | 27–31 |
| *(Early MVP deploy, subset of Phase 14)* | 32–33 |
| Phase 6: Conversation UX & advanced query routing | 34–37 |
| Phase 7: Evaluation platform | 38–42 |
| Phase 8: Observability, feedback & cost controls | 43–46 |
| Phase 9: Document lifecycle & zero-downtime reindexing | 47–49 |
| Phase 10: Connectors & permission synchronization | 50–52 |
| Phase 11: Local/cloud model policy | 53–54 |
| Phase 12: Security hardening | 55–57 |
| Phase 13: Performance/resilience | 58–59 |
| Phase 14: Production CI/CD & deployment | 60–62 (plus 32–33) |
| Phase 15: Portfolio polish & release evidence | 63–65 |

| Frontend phase | Sessions |
|---|---|
| FE-0 Design foundation | 05 |
| FE-1 Application shell | 10, 11 |
| FE-2 Knowledge + ingestion | 15, 21 |
| FE-3 Search | 25 |
| FE-4 Ask + evidence | 30, 31 |
| FE-5 Projects + comparison | 36, 37 |
| FE-6 Admin / access / audit | 11 (basic), 52, 54, 57 |
| FE-7 Retrieval debugger + evaluation | 26, 42 |
| FE-8 Observe | 46 |
| FE-9 Portfolio landing | 63 |
| FE-10 Refinement | 64 |

---

## Appendix D — Mandatory security cases (plan §39.4)

All are consolidated in `tests/security/` in Session 56. Most are first written earlier.

| ID | Case | First written in | Consolidated |
|---|---|---|---|
| SEC-01 | Org A vs Org B cross-tenant query | 08, 25 | 56 |
| SEC-02 | IDOR on document URL/API | 09, 13 | 56 |
| SEC-03 | Restricted document exact-title probing | 25 | 56 |
| SEC-04 | Permission revoked after embedding | 23, 52 | 56 |
| SEC-05 | Deleted document search | 49 | 56 |
| SEC-06 | Poisoned text "ignore previous instructions" | 19, 28 | 56 |
| SEC-07 | Hidden Unicode instruction | 18, 19 | 56 |
| SEC-08 | Malicious Markdown/XSS output | 30, 55 | 56 |
| SEC-09 | SSRF crawler request to local/private address | 50 | 56 |
| SEC-10 | Zip/decompression bomb fixture | 14 | 56 |
| SEC-11 | Overlarge file | 13, 14 | 56 |
| SEC-12 | Leaked cache key attempt (cross-tenant reuse) | 22 | 56 |
| SEC-13 | Local-only KB monitored for external provider calls | 54 | 56 |
| SEC-14 | Prompt asks the model to reveal inaccessible documents | 28 | 56 |
| SEC-15 | Source citation ID tampering | 28, 36 | 56 |

---

## Appendix E — Risks to this session plan

| Risk | Mitigation |
|---|---|
| **Scope creep / never finishing** | One session at a time, strict gates, plan §2.3 non-goals, and new ideas go to `agent.md` §8 as `Later` |
| **Free-tier terms change** (HF, Neon, B2, Auth0, Groq, Gemini) | Re-verify in S32 and S60 (I-001). Storage, LLM, identity and search all sit behind interfaces, so switching providers is mostly configuration |
| **Laptop too weak** for the full stack or local models | Compose profiles, worker concurrency 1, Groq instead of Ollama for development (synthetic data only) |
| **A session turns out too big** | Split into `NNa`/`NNb`, add tracker rows in `agent.md`, never renumber later sessions |
| **Tests postponed** | The §2.4 definition of done requires tests every session, and CI blocks merges |
| **Free LLM quotas run out mid-evaluation** | Judge caching, resumable runs, FakeLLM for CI, nightly full runs |
| **Hosted demo sleeps** (HF 48 h sleep, Neon scale-to-zero) | Expected and documented. Optional light keep-warm ping. Cold starts noted in the runbook |
| **Losing context between sessions/agents** | `agent.md` update protocol at the end of every session, plus CLAUDE.md/AGENTS.md pointing to it |
