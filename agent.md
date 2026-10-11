# agent.md — KnowledgeOS Handoff & Progress Log

> **This is the single source of truth for "where are we?"**
> Any developer or AI agent picking up this project must read this file first, then do the next session from `session.md`, then update this file before stopping.

---

## 0. Read order for anyone joining

1. **This file (`agent.md`)**: current status, what's done, what's broken, what's next.
2. **`session.md`**: find the session listed under *Next session* below. Do only that session.
3. **`plan.md`**: read only the `§` sections that the session references. `plan.md` is the architecture spec and is never edited during normal work (see §10 for deviations).
4. **`docs/adr/`** (once it exists): why key decisions were made.

**Golden rule:** do one session at a time, never skip a gate, and always leave this file accurate.

---

## 1. Current status

| Field | Value |
|---|---|
| **Project phase** | Building: Sprint 0 |
| **Current sprint** | Sprint 0: Foundation |
| **Last completed session** | Session 02: Local infrastructure (Docker Compose) |
| **Next session** | **Session 03: Backend core skeleton** |
| **Sessions done** | 2 / 65 (3%) |
| **Last gate passed** | none (next gate: **G0**, after Session 05) |
| **Repository** | https://github.com/AbrarUI12/KnowledgeOS (public, branch `main`) |
| **Live environments** | none yet (staging planned in Session 33, production in Session 62) |
| **Blockers** | none |
| **Last updated** | 2026-10-12, by Claude (Session 02) |

---

## 2. Update protocol (mandatory at the end of every session)

Before you stop working, **every time**:

1. **Status block (§1):** update last completed session, next session, sessions done, last gate, blockers, last-updated date and author.
2. **Progress tracker (§5):** set the session row to `☑ Done` (or `◐ Partial` with a reason) and fill in date and commit hash.
3. **Gates tracker (§6):** if the session closed a gate, mark it passed and link the evidence (test run, report, screenshot path).
4. **Session log (§7):** add a new entry **at the top** using the template. Be specific: list real file paths, real commands, real test results.
5. **Open issues (§8):** add anything left broken, skipped or deferred. Close items you fixed.
6. **Decisions (§9) / deviations (§10):** record any choice that differs from `session.md` or `plan.md`, with the reason.
7. **How to run (§4):** if setup, run or test commands changed, update them. A newcomer must be able to copy-paste them.
8. **Accounts register (§11):** if you introduced a new external service or environment variable, add it (**names only, never values**).
9. Commit with the message suggested by the session (Conventional Commits), e.g. `git commit -m "docs(agent): close session 07"` or as part of the session's final commit.

### Rules

- **Never write secrets** (API keys, passwords, tokens, connection strings with passwords) in this file. Write the env var *name* only.
- **Be factual.** If tests were not run, say so. If something "works on my machine" only, say that.
- **Partial sessions are fine.** Mark `◐ Partial`, explain exactly what remains, and make the remaining items the first tasks of the next sitting.
- **Do not rewrite history.** Session log entries are append-only. Correct mistakes with a new note.
- Keep entries short but complete. A good entry lets someone resume in under 10 minutes.

---

## 3. Locked decisions (summary)

Full detail is in `session.md` → *Locked decisions*. Constraint: **the whole project must run at $0** (free tiers and open models only).

| Concern | Local development | Deployed (free tier) |
|---|---|---|
| Frontend | Next.js + TypeScript on host (`pnpm dev`) | Vercel Hobby |
| Backend (API, workers, dispatcher, scheduler) | FastAPI + Celery as separate Docker Compose services | One Hugging Face Docker Space (CPU Basic, 2 vCPU / 16 GB), processes run under supervisord. Staging = second Space |
| Database | `pgvector/pgvector` Postgres container | Neon Free (pgvector, branches) |
| Redis | container | in-container Redis on the Space (non-authoritative) |
| Object storage | MinIO | Backblaze B2 (S3-compatible). Cloudflare R2 is an alternative if a payment method is available |
| Identity (OIDC) | Keycloak container | Auth0 Free (or Zitadel Cloud free) |
| Embeddings | Qwen3-Embedding-0.6B (1024-d), in-process | same (in-process, $0, local) |
| Reranker | bge-reranker-v2-m3 (or Qwen3-Reranker-0.6B seq-cls), ONNX on CPU | same |
| Generation LLM | Ollama (OpenAI-compatible) | Groq free tier → Gemini free tier fallback via one OpenAI-compatible adapter |
| Malware scan | ClamAV container | ClamAV in the Space image |
| Tracing / metrics | `grafana/otel-lgtm` container | Langfuse Cloud Hobby + Grafana Cloud Free |
| CI/CD | GitHub Actions | GitHub Actions + GHCR (public repo) |

**Data rule:** free cloud LLM tiers may keep or train on prompts, so use **only synthetic/demo documents** with cloud generation. Local-only knowledge bases use local models.

---

## 4. How to run

> Fill these in as the project is built. Every command here must be tested. Mark untested commands with `(untested)`.

### 4.1 Prerequisites
- Windows 11 + **Docker Desktop (WSL2 backend)**. Celery, Docling, OCR and ClamAV run only inside Linux containers.
- Tested versions (Session 01): Git, **uv 0.12** (it downloads Python **3.12**, pinned in `apps/api/.python-version`), **Node.js 24**, **pnpm 12.11** (pinned via `packageManager` in root `package.json`), **GNU make 4.x**, **pre-commit 4.6**.
- Windows installs used (Session 01):
  - pnpm: `corepack enable --install-directory "$HOME\.local\bin" pnpm`. Plain `corepack enable` fails with EPERM because it can't write to `C:\Program Files\nodejs`.
  - make: `winget install ezwinports.make`, then add `%LOCALAPPDATA%\Microsoft\WinGet\Packages\ezwinports.make_Microsoft.Winget.Source_8wekyb3d8bbwe\bin` to the user PATH (winget did not create a link).
  - pre-commit: `uv tool install pre-commit`, then `uv tool update-shell` (adds `~\.local\bin` to PATH).
  - **Restart the terminal / VS Code** after these so PATH changes apply.

### 4.2 First-time setup
```bash
git clone https://github.com/AbrarUI12/KnowledgeOS.git && cd KnowledgeOS
make install        # uv sync (apps/api) + pnpm install (workspace) + pre-commit install
make lint typecheck test
```
*(Sessions 02–03 add the Docker stack and `.env` setup.)*

### 4.3 Start the local stack
Docker Desktop must be running (installed at `%LOCALAPPDATA%\Programs\DockerDesktop`).
```bash
make up            # core: postgres, redis, minio (+ bucket init), keycloak, mailpit. Creates .env from .env.example if missing
make up-full       # core + clamav (~1.9 GB RAM)
make infra-check   # verifies every service (extensions, DB roles, RLS bypass off, buckets, OIDC issuer + dev login)
make ps | logs | psql | down
make reset         # DELETES all local volumes (fresh DB, realm re-import)
```
| Service | URL / port | Dev credentials |
|---|---|---|
| PostgreSQL | `localhost:5433` (not 5432, see D-009) | app `knowledgeos_app`/`app_dev_password`, owner `knowledgeos_owner`/`owner_dev_password`, superuser `postgres`/`postgres` |
| Redis | `localhost:6380` (not 6379, see D-009) | – |
| MinIO API / console | http://localhost:9000 / http://localhost:9001 | `kos_minio` / `kos_minio_dev_secret` |
| Keycloak | http://localhost:8080 (realm `knowledgeos`) | admin `admin`/`admin`; users `alice@acme.test`, `bob@acme.test`, `hana@acme.test`, `carol@globex.test`, password `<firstname>-dev-password` |
| Mailpit | http://localhost:8025 (SMTP 1025) | – |
| ClamAV (`full`) | `localhost:3310` | – |

Dev access token (password grant, dev realm only):
`curl -s -X POST http://localhost:8080/realms/knowledgeos/protocol/openid-connect/token -d grant_type=password -d client_id=knowledgeos-cli -d username=alice@acme.test -d password=alice-dev-password -d scope=openid`

### 4.4 Run the API / web / workers
- API: `make api` → http://localhost:8000/health/live returns `{"status":"ok"}`
- Web: `make web` → http://localhost:3000
- *(workers added in Session 16)*

### 4.5 Run tests
- Everything: `make lint typecheck test`
- Backend only: `uv --directory apps/api run pytest`. Frontend only: `pnpm web:test`
- All git hooks: `make hooks` (`pre-commit run --all-files`)
- Note: the frontend typecheck runs `next typegen` first, because Next 16 generates global types such as `LayoutProps` into `.next/`.

### 4.6 Seed demo data
*(filled in Session 25)*

### 4.7 Run evaluations
*(filled in Sessions 38–41)*

### 4.8 Deploy
*(filled in Sessions 32–33, finalised in Sessions 60–62)*

---

## 5. Progress tracker

Status legend: `☐` not started · `◐` partial / in progress · `☑` done · `⊘` skipped (with reason in §10)

| # | Session | Sprint | Gate | Status | Date | Commit | Notes |
|---|---|---|---|---|---|---|---|
| 00 | Planning: plan.md, session.md, agent.md | – | – | ☑ | 2026-10-11 | – | Docs only |
| 01 | Repository bootstrap & tooling | 0 | | ☑ | 2026-10-11 | see log | Python 3.12, Next 16, pnpm 12 |
| 02 | Local infrastructure (Docker Compose) | 0 | | ☑ | 2026-10-12 | see log | PG 5433, Redis 6380, pgsty/minio |
| 03 | Backend core skeleton | 0 | | ☐ | | | |
| 04 | CI pipeline, Dockerfiles & ADRs | 0 | | ☐ | | | |
| 05 | Design system foundation (FE-0) | 0 | G0 | ☐ | | | |
| 06 | Identity & organization schema | 1 | | ☐ | | | |
| 07 | OIDC authentication (backend) | 1 | | ☐ | | | |
| 08 | Tenant context, RLS & permission engine | 1 | | ☐ | | | |
| 09 | Organization, member, group & invitation APIs | 1 | | ☐ | | | |
| 10 | Frontend auth, API client & app shell | 1 | | ☐ | | | |
| 11 | Shell completion: command palette, evidence rail, access pages | 1 | G1 | ☐ | | | |
| 12 | Knowledge base & document schema + KB APIs | 2 | | ☐ | | | |
| 13 | Object storage & secure upload flow | 2 | | ☐ | | | |
| 14 | File-safety validation & malware scanning | 2 | | ☐ | | | |
| 15 | Knowledge library & upload UI | 2 | G2 | ☐ | | | |
| 16 | Outbox dispatcher, Celery & job state machine | 3 | | ☐ | | | |
| 17 | Validation stages, canonical model & Docling | 3 | | ☐ | | | |
| 18 | Office/tabular formats, OCR & normalization | 3 | | ☐ | | | |
| 19 | Content-security scanner & structure-aware chunker | 3 | | ☐ | | | |
| 20 | Ingestion reliability & recovery | 3 | | ☐ | | | |
| 21 | Ingestion UI: pipeline, diagnostics, reader/inspect | 3 | G3 | ☐ | | | |
| 22 | Index generations & embedding providers | 4 | | ☐ | | | |
| 23 | Chunk indexing, vector/FTS indexes & ACL materialization | 4 | | ☐ | | | |
| 24 | Permission-aware hybrid search backend | 4 | | ☐ | | | |
| 25 | Search API, demo corpus & Search UI | 4 | | ☐ | | | |
| 26 | Retrieval debugger v1 | 4 | G4 | ☐ | | | |
| 27 | Reranking, RAG profiles & context packing | 5 | | ☐ | | | |
| 28 | LLM gateway, grounded generation & citation validation | 5 | | ☐ | | | |
| 29 | SSE streaming, evidence status & conflicts | 5 | | ☐ | | | |
| 30 | Ask workspace UI | 5 | | ☐ | | | |
| 31 | Evidence rail, source viewer & feedback | 5 | G5 | ☐ | | | |
| 32 | Free-tier accounts & deployable backend image | 6 | | ☐ | | | |
| 33 | MVP staging deployment | 6 | M1 | ☐ | | | |
| 34 | Conversations, query rewrite & query router | 7 | | ☐ | | | |
| 35 | Comparison, summary & guarded query paths | 7 | | ☐ | | | |
| 36 | Conversation UI & Projects | 7 | | ☐ | | | |
| 37 | Compare / Matrix view | 7 | G6 | ☐ | | | |
| 38 | Evaluation schema, runner & retrieval metrics | 8 | | ☐ | | | |
| 39 | Evaluation corpus & golden set part 1 | 8 | | ☐ | | | |
| 40 | Golden set part 2 (200 cases) | 8 | | ☐ | | | |
| 41 | Generation metrics, security gates & CI smoke eval | 8 | | ☐ | | | |
| 42 | Evaluation lab UI & promotion gate | 8 | G7 | ☐ | | | |
| 43 | OpenTelemetry & Langfuse tracing | 9 | | ☐ | | | |
| 44 | Metrics, dashboards & alerts | 9 | | ☐ | | | |
| 45 | Usage ledger, budgets, rate limits & quotas | 9 | | ☐ | | | |
| 46 | Observe UI, Home page & feedback review | 9 | G8 | ☐ | | | |
| 47 | Document version replacement & approval | 10 | | ☐ | | | |
| 48 | Index-generation lifecycle & rollback | 10 | | ☐ | | | |
| 49 | Deletion cascade, retention & orphan sweeper | 10 | G9 | ☐ | | | |
| 50 | Connector framework & secure web connector | 11 | | ☐ | | | |
| 51 | Google Drive connector & permission sync | 11 | | ☐ | | | |
| 52 | Sources UI & permission editor | 11 | G10 | ☐ | | | |
| 53 | Local models & policy-enforcing provider router | 12 | | ☐ | | | |
| 54 | Model-policy UI & zero-external-call proof | 12 | G11 | ☐ | | | |
| 55 | Threat model, API keys & web security headers | 13 | | ☐ | | | |
| 56 | Security regression suite & supply-chain scanning | 13 | | ☐ | | | |
| 57 | Audit log UI, API key UI & onboarding | 13 | G12 | ☐ | | | |
| 58 | Benchmark dataset & retrieval performance tuning | 14 | | ☐ | | | |
| 59 | Load tests, chaos tests & benchmark report | 14 | G13 | ☐ | | | |
| 60 | Production images, Terraform & secrets | 15 | | ☐ | | | |
| 61 | Full CD pipeline & release process | 15 | | ☐ | | | |
| 62 | Production launch, backups & runbooks | 15 | G14 | ☐ | | | |
| 63 | Public landing page (FE-9) | 16 | | ☐ | | | |
| 64 | Frontend refinement (FE-10) | 16 | | ☐ | | | |
| 65 | Release evidence & v1.0.0 | 16 | G15 | ☐ | | | |

---

## 6. Gates tracker

A gate is passed only when **every** exit criterion in `session.md` → *Gates & milestones* is demonstrably true. Link the evidence.

| Gate | Meaning (short) | After session | Status | Date | Evidence |
|---|---|---|---|---|---|
| G0 | Local stack runs, CI green, first migration reproducible, design foundation done | 05 | ☐ | | |
| G1 | Two orgs cannot read each other (API + repository), shell usable by keyboard | 11 | ☐ | | |
| G2 | Valid upload → durable version + queued job; malicious fixtures fail safely | 15 | ☐ | | |
| G3 | All core formats → canonical artifacts; worker restart no duplicates; failures retryable | 21 | ☐ | | |
| G4 | Exact + semantic retrieval work; restricted chunks never returned; active generation enforced | 26 | ☐ | | |
| G5 | Valid citations on every answer; abstains on no-answer; poisoned doc cannot override policy | 31 | ☐ | | |
| M1 | Live MVP on staging (Vercel + HF Space + Neon + B2 + Auth0) | 33 | ☐ | | |
| G6 | Follow-ups stay grounded; permission change between turns respected | 37 | ☐ | | |
| G7 | Reproducible eval metrics per profile; security failures block promotion | 42 | ☐ | | |
| G8 | Bad answer traceable end to end; token/cost visible | 46 | ☐ | | |
| G9 | Replaced/deleted content unretrievable; generation rollback works | 49 | ☐ | | |
| G10 | Changed/deleted/repermissioned source data propagates | 52 | ☐ | | |
| G11 | Local-only KB makes zero external model calls (automated test) | 54 | ☐ | | |
| G12 | Security regression suite passes; no open critical/high findings | 57 | ☐ | | |
| G13 | Benchmarks + bottleneck analysis documented; SLOs met or revised with evidence | 59 | ☐ | | |
| G14 | Fresh environment provisioned + deployed from repo; restore/rollback tested | 62 | ☐ | | |
| G15 | Reviewer can understand and run the product without private explanation (v1.0.0) | 65 | ☐ | | |

---

## 7. Session log (newest first)

### Entry template (copy this for each session)

```markdown
### Session NN — <title>  ·  <YYYY-MM-DD>  ·  <author/agent>
**Status:** ☑ Done | ◐ Partial
**Commit(s):** <hash> <message>

**Done**
- <what was built, concretely>

**Files / areas changed**
- `path/to/file.py`: <why>

**Tests**
- Command: `<exact command>` → <result, e.g. 42 passed, 0 failed>
- Not run / skipped: <what and why>

**Decisions & deviations**
- <anything that differs from session.md/plan.md, with the reason; also add to §9/§10>

**Known issues / tech debt**
- <issue>, logged as I-NNN in §8

**Next steps**
- <first thing the next person should do>
```

---

### Session 02 — Local infrastructure (Docker Compose)  ·  2026-10-12  ·  Claude
**Status:** ☑ Done
**Commit(s):** `chore(infra): local docker compose stack (session 02)`

**Done**
- `docker-compose.yml` with profiles: default/core (postgres `pgvector/pgvector:pg17`, `redis:7-alpine`, `pgsty/minio`, Keycloak 26.8, Mailpit), `full` (+ `clamav/clamav:stable`), `init` (one-shot `minio-init`). Healthchecks on all services.
- Postgres init: `01-extensions.sql` (vector, pg_trgm) and `02-roles.sh`: `knowledgeos_owner` (owns DB + schema `public`), `knowledgeos_app` and `knowledgeos_dispatcher` (NOSUPERUSER, NOBYPASSRLS), default privileges giving the app role DML on owner-created tables, `CREATE` on `public` revoked from PUBLIC, separate `keycloak` DB/role.
- MinIO init (`infra/docker/minio/minio-init.sh`): private buckets `kos-quarantine`, `kos-trusted`, `kos-artifacts`, idempotent 7-day expiry on quarantine (`mc ilm import`). CORS origin via `MINIO_API_CORS_ALLOW_ORIGIN`.
- Keycloak realm import (`infra/docker/keycloak/realm-knowledgeos.json`): clients `knowledgeos-web` (confidential + PKCE S256), `knowledgeos-api` (audience), `knowledgeos-cli` (public, password grant, dev only), audience mapper → `aud: knowledgeos-api`, 4 dev users. `KC_HOSTNAME=http://localhost:8080` + dynamic backchannel so the issuer is identical for browser and containers.
- `.env.example` (all names + dev values) and a git-ignored `.env`. Makefile targets `env`, `up`, `up-full`, `down`, `reset`, `logs`, `ps`, `psql`, `infra-check`. `scripts/check_infra.py` verifies every service.
- Ruff (Makefile + pre-commit) now also covers `scripts/`; root `ruff.toml` extends `apps/api/pyproject.toml` so both use one config. `boto3` added as a backend dev dependency (check script; S3 provider comes in S13).

**Tests**
- `make up` → all core services healthy. `make infra-check` → postgres (extensions, roles, **app role cannot bypass RLS**), redis PONG, minio buckets, keycloak issuer + dev login, mailpit: all OK.
- Decoded a dev token: `iss=http://localhost:8080/realms/knowledgeos`, `aud=knowledgeos-api`, `email` present.
- `make up-full` → ClamAV PONG. `make reset && make up` → clean state healthy in ~49 s, realm re-imported.
- `minio-init` run 3× → exactly one lifecycle rule (idempotent).

**Decisions & deviations**
- D-008 (pgsty/minio because the official image is gone) and D-009 (ports 5433/6380) in §9.2.

**Known issues / tech debt**
- I-002 updated with measured memory.
- `pgsty/mc:latest` and `axllent/mailpit:latest` are unpinned (dev-only helpers). Pin them if they ever break.

**Next steps**
- Session 03: backend core (settings, logging, error envelope, async DB, Alembic 0001, `/health/ready`, Testcontainers harness). The stack is up (`make up`).

---

### Session 01 — Repository bootstrap & tooling  ·  2026-10-11  ·  Claude
**Status:** ☑ Done
**Commit(s):** `chore: bootstrap monorepo, tooling and agent onboarding files (session 01)` on `main`

**Done**
- Installed missing tools on the dev machine: pnpm 12.11 (corepack, user bin dir), GNU make (winget), pre-commit 4.6 (uv tool). See §4.1 for the Windows workarounds.
- Created the full plan §6 directory skeleton (`.gitkeep` placeholders), including all `apps/api/app/*` subpackages from §6.
- Backend `apps/api`: uv project (hatchling, package `app`), Python 3.12 pinned, runtime deps (FastAPI, Pydantic 2, pydantic-settings, SQLAlchemy 2 async, asyncpg, Alembic, structlog, httpx, tenacity) and dev deps (ruff, mypy, pytest, pytest-asyncio, pytest-cov, hypothesis, testcontainers, respx, syrupy). Ruff, mypy strict and pytest (markers `unit/integration/security/slow/llm`) configured. `GET /health/live`.
- Frontend `apps/web`: Next.js 16.4 + React 19.3 + Tailwind 4 + TypeScript strict, renamed `@knowledgeos/web`. Vitest + Testing Library + jsdom, Prettier. Plan §27.27 folder layout created. Placeholder home page; Next's starter SVGs removed.
- Root: pnpm workspace (`pnpm-workspace.yaml`, root `package.json` with `web:*` scripts, single root `pnpm-lock.yaml`), `Makefile`, `.pre-commit-config.yaml` (pre-commit-hooks v6, ruff v0.17, gitleaks v8.30), `.editorconfig`, expanded `.gitignore`, `README.md`, `CLAUDE.md` and identical root `AGENTS.md`.

**Files / areas changed**
- `apps/api/pyproject.toml`, `apps/api/uv.lock`, `apps/api/app/main.py`, `apps/api/tests/test_health.py`
- `apps/web/*` (scaffold + `vitest.config.mts`, `tests/setup.ts`, `app/page.test.tsx`, `.prettierrc.json`)
- `Makefile`, `.pre-commit-config.yaml`, `package.json`, `pnpm-workspace.yaml`, `README.md`, `CLAUDE.md`, `AGENTS.md`

**Tests**
- `make lint typecheck test` → Ruff clean, mypy strict "no issues in 30 source files", pytest 1 passed, ESLint clean, Prettier clean, tsc clean, Vitest 1 passed.
- `pnpm web:build` → compiled successfully. `uv run uvicorn app.main:app` → `/health/live` returned `{"status":"ok"}`.
- `pre-commit run --all-files` → all hooks pass, gitleaks finds nothing.
- Fresh-clone check: `git clone` → `make install` → `make lint typecheck test`, all green (run at `D:\kos-cc`, then deleted).

**Decisions & deviations**
- D-007 (hardware → Ollama on the RTX 4060 for local generation) recorded in §9.2.
- `apps/web/AGENTS.md` is **generated by Next.js 16** (it tells agents to read version-specific docs in `node_modules/next/dist/docs/`). Kept and committed on purpose; Next re-creates it on `next dev`.
- `check-yaml` uses `--allow-multiple-documents` because the pnpm 12 lockfile is a multi-document YAML file.

**Known issues / tech debt**
- None new. GitHub Actions CI does not exist yet (Session 04), so nothing enforces checks on push until then.
- I-004: keep clones at a **short path** on Windows. In a very deep folder `next typegen` failed with "path not found" (Windows MAX_PATH).

**Next steps**
- Start **Session 02**: Docker Compose stack (pgvector Postgres, Redis, MinIO, Keycloak, Mailpit, ClamAV profile). Make sure Docker Desktop is running. With 16 GB RAM, give Docker about 8 GB (I-002).

---

### Session 00 — Planning  ·  2026-10-11  ·  Claude (planning session)
**Status:** ☑ Done
**Commit(s):** none (repository not initialised yet; `git init` happens in Session 01)

**Done**
- Read the full architecture spec `plan.md` (45 sections, Phases 0–15, FE-0 to FE-10).
- Wrote `session.md`: 65 sessions in 17 sprints, from repository bootstrap to production deployment and v1.0.0, with goals, tasks, tests, "done when" checks, gates and traceability to plan.md §41 (demos) and §44 (definition of done).
- Wrote this `agent.md` handoff log.
- Locked a **$0 free-tier stack** (see §3) because the project has no budget.

**Files / areas changed**
- `session.md`: new
- `agent.md`: new
- `plan.md`: unchanged

**Tests**
- None (documentation only).

**Decisions & deviations**
- D-001 to D-006 recorded in §9. Free-tier deviations from plan.md recorded in §10.

**Known issues / tech debt**
- I-001: free-tier limits (HF Spaces, Neon, Groq, Gemini, B2, Auth0) change often. Re-verify them in Session 32 and again in Session 60.

**Next steps**
- Start **Session 01** in `session.md`: `git init`, monorepo layout, uv backend project, pnpm Next.js app, Makefile, pre-commit, and `CLAUDE.md` pointing to this file.

---

## 8. Open issues, blockers & tech debt

| ID | Type | Description | Raised (session) | Owner | Status |
|---|---|---|---|---|---|
| I-001 | Risk | Free-tier limits change. Re-verify HF Spaces, Neon, Groq, Gemini, B2 and Auth0 terms before deploying | 00 | – | Open, revisit in S32 and S60 |
| I-002 | Risk | Developer laptop RAM: the full Compose stack (Postgres, Redis, MinIO, Keycloak, ClamAV, worker with models) may need 10+ GB. Use the `core` profile when RAM is tight. **Measured S02:** Docker has 7.4 GB; Keycloak ≈ 1.8 GB, ClamAV ≈ 1.9 GB, the others < 100 MB each; another local project (`retailops-bd`) uses ≈ 1.5 GB. Stop ClamAV (`docker compose stop clamav`) and other projects when running workers/Ollama | 00 | – | Open (measured), revisit in S16/S22 |
| I-003 | Risk | CPU-only reranking may miss the plan's retrieval P95 < 500 ms target. Measure, then tune (ONNX int8, fewer candidates) or revise the target with evidence | 00 | – | Open, revisit in S27 and S58 |
| I-004 | Risk | Windows MAX_PATH: `next typegen` fails when the repo sits in a very deep folder. Keep the clone at a short path such as `D:\projects\KnowledgeOS` | 01 | – | Open (workaround documented) |

Types: `Blocker` · `Bug` · `Tech debt` · `Risk` · `Question`

---

## 9. Decision log

### 9.1 Architecture Decision Records (ADRs)
Written in Session 04 under `docs/adr/`. Index:

| ADR | Title | Status |
|---|---|---|
| ADR-001 | Modular monolith | planned (S04) |
| ADR-002 | PostgreSQL + pgvector first search | planned (S04) |
| ADR-003 | OIDC identity, app-owned authorization | planned (S04) |
| ADR-004 | Tenant RLS strategy | planned (S04) |
| ADR-005 | Async ingestion + transactional outbox | planned (S04) |
| ADR-006 | Provider abstraction | planned (S04) |
| ADR-007 | Index generations | planned (S04) |
| ADR-008 | Free-tier deployment topology | planned (S04) |

### 9.2 Smaller decisions

| ID | Date | Decision | Reason |
|---|---|---|---|
| D-001 | 2026-10-11 | Whole project uses free tiers and open models only | No budget |
| D-002 | 2026-10-11 | Backend deploys to a **Hugging Face Docker Space** instead of Render/Railway | Render free has no background workers and 512 MB RAM (too small for Docling/OCR/models); Railway has no lasting free tier. HF CPU Basic gives 2 vCPU / 16 GB at $0 |
| D-003 | 2026-10-11 | **Backblaze B2** is the default object store, Cloudflare R2 the alternative | R2 asks for a payment method on file; B2's 10 GB free tier does not. Both are S3-compatible, so switching is a config change |
| D-004 | 2026-10-11 | Embeddings and reranker run **in-process with open models** (Qwen3-Embedding-0.6B 1024-d; bge-reranker-v2-m3) | $0, no rate limits, data never leaves the deployment (satisfies local-only policy) |
| D-005 | 2026-10-11 | Generation goes through one **OpenAI-compatible adapter** (Ollama locally; Groq free primary; Gemini free fallback) | One adapter covers many free providers; model IDs stay in config |
| D-007 | 2026-10-11 | Dev machine: 16 GB RAM + RTX 4060 Laptop (8 GB VRAM). Local dev uses **Ollama on the GPU** for generation (7–8B models at Q4, e.g. `qwen3:8b`) and can run embeddings/reranker on CUDA locally; deployed stays CPU | 8 GB VRAM fits a Q4 8B model; 16 GB system RAM means the Compose `full` profile + Ollama together is tight, so use the `core` profile when running local models |
| D-008 | 2026-10-12 | Local MinIO uses **`pgsty/minio`** (pinned `RELEASE.2026-08-04T00-00-00Z`) and `pgsty/mc` | The official `minio/minio` and `minio/mc` images no longer exist on Docker Hub. pgsty is the maintained community build of the same server. Only local dev is affected (deployed storage is B2/R2) |
| D-009 | 2026-10-12 | KnowledgeOS host ports: **Postgres 5433, Redis 6380** | 5432/6379 are used by another local project (`retailops-bd`). Configurable via `POSTGRES_PORT`/`REDIS_PORT` in `.env` |
| D-006 | 2026-10-11 | Hosted identity uses **Auth0 Free**; Keycloak stays for local development | Hosting Keycloak needs a paid always-on instance; the app is IdP-agnostic by design |

---

## 10. Deviations from plan.md

`plan.md` is the target architecture. Record every intentional difference here.

| ID | plan.md reference | Deviation | Reason | Reversible? |
|---|---|---|---|---|
| DV-001 | §4.1, §38.2 | Demo deployment runs api/worker/dispatcher/scheduler in **one container** (supervisord) instead of separate units | Free hosting allows one container; same image and commands, so it splits back out on paid infrastructure | Yes |
| DV-002 | §38.2 | Render/Railway replaced by Hugging Face Spaces | See D-002 | Yes |
| DV-003 | §5.4 | No paid cloud embedding/reranker. Local open models are the default for all KBs | See D-004 | Yes (add provider) |
| DV-004 | §35 | Real spend is $0. The cost ledger records tokens plus **list-price estimates** from a versioned pricing table | Keeps cost analytics meaningful on free tiers | n/a |
| DV-005 | §36.1 | The 100k+ chunk benchmark runs locally, not on hosted Neon (1 GB free storage limit) | Free-tier storage | Yes |
| DV-006 | §38.2 | Redis in the deployed demo runs inside the backend container (ephemeral) | Upstash free quotas can't absorb Celery polling; Redis is non-authoritative per §34.5 | Yes |

---

## 11. Environments & accounts register

**Names only. Never write secret values here.** Real values live in local `.env` files (git-ignored) and in each platform's secret store.

| Service | Purpose | Env var names | Environments | Introduced in |
|---|---|---|---|---|
| PostgreSQL (local container) | Main DB | `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_SUPERUSER(_PASSWORD)`, `KOS_OWNER_PASSWORD`, `KOS_APP_PASSWORD`, `KOS_DISPATCHER_PASSWORD`, `DATABASE_URL`, `DATABASE_MIGRATION_URL` | local | S02 |
| Redis (local container) | Celery broker, rate limits | `REDIS_PORT`, `REDIS_URL` | local | S02 |
| MinIO (local container) | Object storage | `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET_QUARANTINE`, `S3_BUCKET_TRUSTED`, `S3_BUCKET_ARTIFACTS`, `S3_PUBLIC_ENDPOINT_URL`, `S3_REGION`, `S3_FORCE_PATH_STYLE`, `MINIO_PORT`, `MINIO_CONSOLE_PORT` | local | S02 |
| Keycloak (local container) | OIDC | `KEYCLOAK_PORT`, `KEYCLOAK_ADMIN(_PASSWORD)`, `KEYCLOAK_DB_PASSWORD`, `OIDC_ISSUER`, `OIDC_AUDIENCE`, `OIDC_JWKS_URL`, `OIDC_WEB_CLIENT_ID`, `OIDC_WEB_CLIENT_SECRET`, `OIDC_CLI_CLIENT_ID` | local | S02 |
| Mailpit / ClamAV (local containers) | Email, malware scan | `SMTP_HOST`, `SMTP_PORT`, `MAILPIT_UI_PORT`, `CLAMAV_HOST`, `CLAMAV_PORT`, `WEB_ORIGIN` | local | S02 |
| *(more rows added as sessions introduce services: Neon, B2, Auth0, HF, Vercel, Groq, Gemini, Langfuse, Grafana Cloud, Google Drive OAuth)* | | | | |
