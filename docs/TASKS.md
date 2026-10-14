# Tasks: Milestone M1 (first live deployment)

> Who does what, in which order, and the current status, from Session 07 to Session 33 (staging deployment).
> Rules for working on these tasks: [`docs/AGENT_WORKFLOW.md`](AGENT_WORKFLOW.md). Detailed spec of each task: the referenced **session.md** section (its "Tasks" list is the scope, its "Done when" is the bar).

**Milestone:** M1: live MVP on staging (Vercel + HF Space + Neon + B2 + Auth0) · **Status:** IN PROGRESS
**Agents:** Claude (architect, security/DB/integration, reviewer) · Codex (libraries, frontend foundation, Ask experience, reviews Claude) · Cline (UI pages, scripts, local QA)

---

## How to use this file

- **Status values:** `TODO` · `PLANNED` (claimed, not started) · `IN PROGRESS` · `REVIEW` · `BLOCKED` (say why) · `DONE`
- **Update only your own board** (§1). Each agent's rows are in a separate table, so parallel edits don't conflict. Task specs (§4) are static. Only Claude edits them, via a reviewed PR.
- **Dependencies:**
  - **hard**: must be merged before you start.
  - **contract**: build against the T1.0 contracts with fakes/mocks; finish the integration test once the provider task merges.
- **Picking your next task:** the lowest wave in your board whose hard dependencies are `DONE`. Reviews come before new tasks.
- **Every task's PR** links its task ID and gets reviewed by the listed reviewer (Codex/Cline → Claude, Claude → Codex).

---

## 1. Boards (live status, edit your own table only)

### Claude

| ID | Task | Wave | Session | Status | Branch | PR |
|---|---|---|---|---|---|---|
| T0.1 | Multi-agent workflow bootstrap | – | – | DONE | ai/claude-agent-workflow | #9 |
| T1.0 | Contracts: provider Protocols, core models, API + SSE schemas | 0 | – | DONE | ai/claude-t1.0-contracts | #11 |
| T1.1 | OIDC authentication (backend) | 1 | S07 | DONE | ai/claude-t1.1-oidc | #13 |
| T1.2 | Tenant context, RLS & permission engine | 1 | S08 | DONE | ai/claude-t1.2-rls | #23 (was #15) |
| T1.3 | Org / member / group / invitation APIs + audit | 2 | S09 | DONE | ai/claude-t1.3-org-apis | #19 |
| T2.1 | KB & document schema + KB APIs + RLS meta-test | 2 | S12 | REVIEW | ai/claude-t2.1-kb-schema | #25 |
| T2.4 | Upload & document endpoints | 3 | S13 | TODO | | |
| T3.1 | Outbox dispatcher, Celery & job state machine | 3 | S16 | TODO | | |
| T3.5 | Ingestion stage wiring + chunks schema + approvals | 4 | S17–S19 | TODO | | |
| T3.6 | Ingestion reliability & recovery | 4 | S20 | TODO | | |
| T4.2 | Index generations (DB) + chunk indexing & ACL materialization | 5 | S22–S23 | TODO | | |
| T4.4 | Permission-aware hybrid search backend | 5 | S24 | TODO | | |
| T4.6 | Search API, demo seed loader, debug API | 6 | S25–S26 | TODO | | |
| T5.3 | RAG profiles, model policies & `/query` orchestration | 7 | S27–S28 | TODO | | |
| T5.4 | SSE streaming, evidence status, conflicts + evidence endpoints | 7 | S29, S31 | TODO | | |
| T6.1 | Free-tier accounts & deployable backend image | 9 | S32 | TODO | | |
| T6.3 | MVP staging deployment | 9 | S33 | TODO | | |

### Codex

| ID | Task | Wave | Session | Status | Branch | PR |
|---|---|---|---|---|---|---|
| T2.3 | File-safety validation & malware scanners | 0 | S14 | DONE | ai/codex-t2.3-file-validation | #10 |
| T2.2 | ObjectStore providers (S3/MinIO/B2 + in-memory) | 1 | S13 | DONE | ai/codex-t2.2-object-store | #14 |
| T1.4 | Frontend auth, typed API client & app shell | 1 | S10, S11 | TODO | | |
| T3.2 | Docling parser library (PDF/DOCX/HTML/MD) | 2 | S17 | TODO | | |
| T3.3 | Office/tabular formats, OCR & normalization library | 3 | S18 | TODO | | |
| T3.4 | Content-security scanner & structure-aware chunker | 4 | S19 | TODO | | |
| T4.1 | Embedding providers | 4 | S22 | TODO | | |
| T5.1 | Reranker, context packer & source aliases | 5 | S27 | TODO | | |
| T5.2 | LLM gateway, prompts, abstention & citation validator | 5 | S28 | TODO | | |
| T4.8 | Retrieval debugger UI | 6 | S26 | TODO | | |
| T5.5 | Ask workspace UI | 7 | S30 | TODO | | |
| T5.7 | Evidence rail, source viewer & feedback UI | 8 | S31 | TODO | | |

### Cline

| ID | Task | Wave | Session | Status | Branch | PR |
|---|---|---|---|---|---|---|
| T4.5 | Demo corpus file generator | 0 | S25 | DONE | ai/cline-t4.5-demo-corpus | #12 |
| T1.8 | `scripts/get_token.py` | 0 | S07 | DONE | ai/cline-t4.5-demo-corpus | #12 |
| T4.3 | RRF fusion module | 1 | S24 | REVIEW | ai/cline-t4.3-rrf-fusion | #16 |
| T1.5 | Command palette, shortcuts, status center | 2 | S11 | TODO | | |
| T1.6 | Access pages: Members & Groups | 2 | S11 | TODO | | |
| T1.7 | Playwright E2E harness + first journeys | 2 | S11 | TODO | | |
| T2.5 | Knowledge library & upload UI | 3 | S15 | TODO | | |
| T2.6 | `scripts/upload_file.py` | 4 | S13 | REVIEW | ai/cline-t2.6-upload-script | |
| T3.7 | Ingestion UI: pipeline, diagnostics, reader/inspect, approvals | 4 | S21 | TODO | | |
| T5.6 | Answer-state components, copy & feedback controls | 5 | S31 | TODO | | |
| T4.7 | Search UI + demo journeys | 6 | S25 | TODO | | |
| T6.2 | Staging smoke script, Playwright smoke & keep-warm | 8 | S33 | TODO | | |
| QA | Local QA pass at each gate (G1–G5, M1) | per gate | – | – | | |

---

## 2. Gates (Claude verifies, tags, and records evidence in agent.md §6)

| Gate | After wave | Needs DONE | Cline QA | Status |
|---|---|---|---|---|
| **G1** identity & tenancy | 2 | T1.0–T1.8 | yes | TODO |
| **G2** secure upload | 3 | T2.1–T2.5 | yes | TODO |
| **G3** reliable ingestion | 4 | T3.1–T3.7, T2.6 | yes | TODO |
| **G4** retrieval | 6 | T4.1–T4.8 | yes | TODO |
| **G5** grounded answers (MVP core) | 8 | T5.1–T5.7 | yes | TODO |
| **M1** live staging | 9 | T6.1–T6.3 | yes (on staging) | TODO |

Gate criteria: session.md §6. Gate checks that need scripts (`test_gate_g4.py`, `test_gate_g5.py`) are written by Claude as part of T4.6 / T5.4.

## 3. Waves (what runs at the same time)

| Wave | Claude | Codex | Cline | Ends with |
|---|---|---|---|---|
| 0 | T1.0 | T2.3 | T4.5, T1.8 | contracts merged |
| 1 | T1.1, T1.2 | T2.2, T1.4 | T4.3 | |
| 2 | T1.3, T2.1 | T3.2 | T1.5, T1.6, T1.7 | **G1** |
| 3 | T2.4, T3.1 | T3.3 | T2.5 | **G2** |
| 4 | T3.5, T3.6 | T3.4, T4.1 | T3.7, T2.6 | **G3** |
| 5 | T4.2, T4.4 | T5.1, T5.2 | T5.6 | |
| 6 | T4.6 | T4.8 | T4.7 | **G4** |
| 7 | T5.3, T5.4 | T5.5 | QA, fixes | |
| 8 | integration fixes | T5.7 | T6.2 (against local), QA | **G5** |
| 9 | T6.1, T6.3 | fixes, reviews | T6.2 (against staging), QA | **M1** |

Waves are a guide, not a schedule. An agent that finishes early takes its next task whose hard dependencies are DONE, or helps with reviews.

---

## 4. Task specifications (static)

Format: owner → reviewer · session.md section(s) · dependencies · owned paths · scope · acceptance criteria. "Scope" lists only what this task takes from the session; the rest of that session belongs to the other tasks named.

### Sprint 1: identity, tenancy & authorization → G1

#### T1.0 Contracts (Claude → Codex)
- **Session:** cross-cutting (enables parallel work; ADR-006, plan §25, §26, §23, §10.1, §12)
- **Depends on:** –
- **Owned paths:** `app/providers/{storage,scanning,embeddings,rerankers,llm,search,identity}/base.py`, `app/ingestion/canonical.py`, `app/ingestion/chunking/types.py`, `app/ingestion/parsing/base.py`, `app/security/content_types.py`, `app/rag/types.py`, `app/domain/enums.py`, `app/domain/schemas/`, `app/api/v1/{_stub,identity,knowledge,retrieval}.py`, `app/export_openapi.py`, `packages/contracts/openapi.json`, `tests/fakes/`, `docs/api/sse-events.md`
- **Scope:**
  - Python Protocols with docstrings: `ObjectStore` (presign_put, head, get_stream, put, copy, delete, exists), `DocumentParser`, `ContentScanner`, `Chunker`, `EmbeddingProvider` (`embed_documents`, `embed_query`, `model_id`, `dimension`, `is_external`), `RerankerProvider`, `LLMProvider` (`generate`, `stream`, usage), `SearchBackend` (dense, lexical, hybrid), `IdentityVerifier`.
  - Pydantic models: `CanonicalDocument` + `Block` (plan §10.1), `ChunkDraft` (§12, incl. `embedding_text`, page/slide/row ranges, `content_hash`), RAG types (`Candidate`, `RankedHit`, `EvidenceItem`, `SourceAlias`, `Usage`).
  - API schemas (request/response) for `/v1/me`, organizations, members, invitations, groups, knowledge bases + permissions, uploads, documents, versions, ingestion jobs, search, query, query runs, debug, feedback. Registered as **stub routes returning 501** so the OpenAPI spec and the TS client exist before the implementations.
  - `docs/api/sse-events.md`: event names and payload schemas (meta, stage, sources, answer_delta, citation, done, error).
  - `python -m app.export_openapi` writes `packages/contracts/openapi.json`.
- **Note:** the malware-scanner (`MalwareScanner`, `providers/scanning/base.py`) and file-validation (`validate_file`, `security/file_validation.py`) contracts are **T2.3's APIs**, adopted after review of #10.
- **Acceptance:** contracts import cleanly, mypy strict passes; OpenAPI exported and committed; each Protocol has a fake implementation in `tests/fakes/` (used by others' tests); reviewed by Codex for usability.

#### T1.1 OIDC authentication (Claude → Codex)
- **Session:** S07 (all tasks except `scripts/get_token.py`, which is T1.8)
- **Depends on:** hard T1.0
- **Acceptance:** S07 "Done when"; all negative JWT tests (expired, wrong aud/iss, bad signature, alg none, unknown kid) → 401; JIT provisioning creates one user; integration test with a real Keycloak token.

#### T1.2 Tenant context, RLS & permission engine (Claude → Codex)
- **Session:** S08 (all)
- **Depends on:** hard T1.1
- **Acceptance:** S08 "Done when"; tenant-isolation suite as `knowledgeos_app` (cross-org exact-id → nothing; missing context → nothing; wrong `organization_id` insert rejected); Hypothesis permission invariants; readiness asserts the runtime role can't bypass RLS; cross-org API → 404.

#### T1.3 Org / member / group / invitation APIs (Claude → Codex)
- **Session:** S09 (all)
- **Depends on:** hard T1.2
- **Acceptance:** S09 "Done when": last-owner protection, IDOR → 404, pagination stable under inserts, idempotent replay, exactly one audit row per mutation; `docs/api/errors.md` updated; OpenAPI regenerated.

#### T1.4 Frontend auth, typed API client & app shell (Codex → Claude)
- **Session:** S10 (all) + from S11: evidence-rail container (resizable by pointer and keyboard, persisted width), responsive modes (§27.5 breakpoints), route transitions, landmarks/skip link in the shell
- **Depends on:** hard T1.0 · contract T1.1 (`/v1/me`), T1.3 (orgs)
- **Owned paths:** `apps/web/lib/{api,auth}/`, `apps/web/components/shell/`, `apps/web/app/(app)/` layout + route stubs, `apps/web/proxy.ts` (Next 16 renamed `middleware` to `proxy`), `packages/contracts/`
- **Notes:** read `apps/web/node_modules/next/dist/docs/` first (Next 16 differs from older versions). Tokens stay in memory, never localStorage (ARCHITECTURE: Authentication). Add `AUTH_URL` to `.env.example`. `pnpm gen:api` + CI drift check (`git diff --exit-code packages/contracts`).
- **Acceptance:** S10 "Done when" (login → shell with real memberships, create org, logout, token refresh); rail and responsive behaviour work by keyboard; Vitest for permission helper and error parsing.

#### T1.5 Command palette, shortcuts, status center (Cline → Claude)
- **Session:** S11: command palette (cmdk, Ctrl/Cmd+K, role-filtered admin actions), shortcut registry + help dialog (`?`, `/`, `Esc`), status-center popover (placeholder events), toast policy helper (§27.23)
- **Depends on:** hard T1.4
- **Owned paths:** `apps/web/components/command/`, `apps/web/components/feedback/`, `apps/web/lib/shortcuts.ts`
- **Acceptance:** palette opens by keyboard, navigates pages, closes with Esc and restores focus; shortcut registry unit tests; axe clean.

#### T1.6 Access pages: Members & Groups (Cline → Claude)
- **Session:** S11: Members (list, invite dialog with copyable link, role change, remove) and Groups (list, create, manage members)
- **Depends on:** hard T1.4 · contract T1.3
- **Owned paths:** `apps/web/features/access/`, `apps/web/app/(app)/[org]/access/`
- **Acceptance:** all actions go through the generated client; permission-aware visibility (UI hides, API still enforces); empty/loading/error states; component tests.

#### T1.7 Playwright harness + first journeys (Cline → Claude)
- **Session:** S11: Playwright setup, Keycloak login global setup, storageState per dev user, journeys "login → shell" and "Carol (Globex) can't see Acme", axe on shell routes, CI e2e job on the Compose core stack
- **Depends on:** hard T1.4 (T1.6 for the access journey)
- **Owned paths:** `apps/web/tests/e2e/`, `apps/web/playwright.config.ts`, the e2e job in `.github/workflows/ci.yml` (coordinate with Claude in the PR)
- **Acceptance:** journeys green locally and in CI; documented in `docs/TESTING.md` (E2E command).

#### T1.8 `scripts/get_token.py` (Cline → Claude)
- **Session:** S07: dev-only password grant via `knowledgeos-cli` for the 4 dev users; prints the access token; refuses to run if `OIDC_ISSUER` isn't localhost
- **Depends on:** –
- **Acceptance:** `uv --directory apps/api run python ../../scripts/get_token.py alice` prints a token whose `aud` is `knowledgeos-api`; documented in agent.md §4.3.

**G1** (Claude): session.md §6 G1 criteria + Cline QA pass → tag `gate-G1`.

### Sprint 2: knowledge bases & secure upload → G2

#### T2.1 KB & document schema + KB APIs (Claude → Codex)
- **Session:** S12 (all)
- **Depends on:** hard T1.3
- **Acceptance:** S12 "Done when"; RLS meta-test (every table with `organization_id` has forced RLS) passes and guards all later migrations.

#### T2.2 ObjectStore providers (Codex → Claude)
- **Session:** S13: `S3ObjectStore` (MinIO/B2/R2; path-style option; **separate public endpoint for presigning**), `InMemoryObjectStore`, key-scheme helpers (never user filenames)
- **Depends on:** contract T1.0 (`ObjectStore`)
- **Owned paths:** `app/providers/storage/`
- **Acceptance:** unit tests with in-memory store; integration test against a MinIO Testcontainer (presign → PUT via httpx → head/get/copy/delete); no secrets in logs.

#### T2.3 File-safety validation & malware scanners (Codex → Claude)
- **Session:** S14 (all)
- **Depends on:** – (validation is pure; scanner implements T1.0's `MalwareScanner`)
- **Owned paths:** `app/security/file_validation.py`, `app/providers/scanning/`, `tests/fixtures/files/` (valid samples only)
- **Acceptance:** S14 "Done when"; malicious fixtures generated at runtime (never committed); Hypothesis "never raises on random bytes"; ClamAV detects EICAR (integration, `full` profile).

#### T2.4 Upload & document endpoints (Claude → Codex)
- **Session:** S13: upload/complete endpoints (one transaction: document + version + job + outbox + audit), replacement start, documents/versions/jobs read APIs, delete stub, provenance fields
- **Depends on:** hard T2.1, T2.2
- **Acceptance:** S13 "Done when" (except the script, T2.6); size mismatch rejected; double-complete idempotent; cross-org upload id → 404; failure mid-transaction persists nothing.

#### T2.5 Knowledge library & upload UI (Cline → Claude)
- **Session:** S15 (all)
- **Depends on:** hard T1.4 · contract T2.1, T2.4
- **Owned paths:** `apps/web/features/knowledge/`, `apps/web/features/documents/` (table), routes under `apps/web/app/(app)/[org]/knowledge/`
- **Acceptance:** S15 "Done when"; virtualization works with 1,000 mocked rows; XHR upload progress; pipeline status mapping unit-tested.

#### T2.6 `scripts/upload_file.py` (Cline → Claude)
- **Session:** S13: CLI that gets a token (T1.8), calls presign, PUTs the file, completes, and prints document/version/job IDs
- **Depends on:** hard T2.4, T1.8
- **Acceptance:** creates a queued job against the local stack; clear errors for rejected files.

**G2** (Claude): §6 G2 + Cline QA → tag `gate-G2`.

### Sprint 3: reliable ingestion → G3

#### T3.1 Outbox dispatcher, Celery & state machine (Claude → Codex)
- **Session:** S16 (all)
- **Depends on:** hard T2.4
- **Acceptance:** S16 "Done when" (upload reaches READY through stub stages); duplicate delivery single-effect; lease prevents double processing; crash between stages resumes from checkpoint.

#### T3.2 Docling parser library (Codex → Claude)
- **Session:** S17: `DoclingParser` (PDF native, DOCX, HTML, Markdown) → `CanonicalDocument` with pages, bboxes, heading paths, tables, reading order; subprocess isolation with timeout + memory limit; CPU-only torch dependency config (uv index); Docling model pre-download script
- **Depends on:** contract T1.0 (`CanonicalDocument`, `DocumentParser`)
- **Owned paths:** `app/ingestion/parsing/` (implementations), `tests/fixtures/documents/`, `scripts/download_docling_models.py`
- **Acceptance:** golden snapshot tests (syrupy) per format; timeout path tested; library is DB-free (takes bytes/path, returns the model).

#### T3.3 Office/tabular formats, OCR & normalization (Codex → Claude)
- **Session:** S18 (all, library parts)
- **Depends on:** hard T3.2
- **Owned paths:** `app/ingestion/parsing/` (additional parsers), `app/ingestion/normalize.py`
- **Acceptance:** S18 "Done when"; snapshots for PPTX/XLSX/CSV/scanned PDF/PNG; normalization unit tests (NFC, zero-width, bidi, header/footer furniture).

#### T3.4 Content-security scanner & chunker (Codex → Claude)
- **Session:** S19: content scanner (rules in `configs/policies/content_scan.yaml`, outcomes clean/flagged/quarantined/rejected), structure-aware parent/child chunker + `recursive_fixed` alternative
- **Depends on:** hard T3.3
- **Owned paths:** `app/security/content_scanner.py`, `configs/policies/content_scan.yaml`, `app/ingestion/chunking/` (implementations)
- **Acceptance:** one test per scanner rule + poisoned fixture flagged; Hypothesis chunker invariants from S19; deterministic output.

#### T3.5 Ingestion stage wiring + chunks schema + approvals (Claude → Codex)
- **Session:** S17–S19 non-library parts: VALIDATING, MALWARE_SCAN (+ promotion to trusted), PARSING (artifact persistence), NORMALIZING, SECURITY_SCAN, CHUNKING stages; migration for `index_generations` + `chunks` base; approval endpoints + PENDING_APPROVAL; worker Dockerfile system packages (Tesseract etc.)
- **Depends on:** hard T3.1, T2.3, T3.2, T3.3 · contract T3.4 (`ContentScanner`, `Chunker`: wire the SECURITY_SCAN and CHUNKING stages against the fakes, finish once T3.4 merges)
- **Acceptance:** uploads of every core format reach chunked state; poisoned doc flagged/held per policy; re-running CHUNKING never duplicates rows.

#### T3.6 Ingestion reliability & recovery (Claude → Codex)
- **Session:** S20 (all)
- **Depends on:** hard T3.5
- **Acceptance:** S20 "Done when"; kill-worker test passes (identical chunk count); retry resumes from the failed stage.

#### T3.7 Ingestion UI (Cline → Claude)
- **Session:** S21 (all): live pipeline rows, failure diagnostics + retry, KB jobs view, document Reader mode (canonical-block renderer) and Inspect mode (provenance, block tree, chunk boundaries, scan findings, timeline), approval queue
- **Depends on:** hard T2.5 · contract T3.6
- **Owned paths:** `apps/web/features/ingestion/`, `apps/web/features/documents/` (detail, reader, inspect)
- **Notes:** build the canonical-block renderer as a reusable component (`features/documents/canonical-renderer`); Codex reuses it in T5.7.
- **Acceptance:** S21 "Done when" for the UI; Playwright: upload → READY → Inspect shows chunks; failing fixture shows error + retry.

**G3** (Claude): §6 G3 + Cline QA → tag `gate-G3`.

### Sprint 4: indexing & retrieval → G4

#### T4.1 Embedding providers (Codex → Claude)
- **Session:** S22: `SentenceTransformersEmbeddingProvider` (Qwen3-Embedding-0.6B, 1024-d, query prompt, normalized, CUDA if available locally, CPU deployed), `OpenAICompatibleEmbeddingProvider`, `FakeEmbeddingProvider`, `scripts/download_models.py`
- **Depends on:** contract T1.0 (`EmbeddingProvider`)
- **Owned paths:** `app/providers/embeddings/`, `scripts/download_models.py`
- **Acceptance:** contract tests with the fake; `slow` test loads the real model and asserts dimension 1024; dimension-mismatch guard; no silent fallback.

#### T4.2 Index generations (DB) + chunk indexing & ACL materialization (Claude → Codex)
- **Session:** S22 DB parts (generation service, embedding reuse within the org, EMBEDDING/INDEXING/VERIFYING stages, HF cache volume) + S23 (all)
- **Depends on:** hard T3.6, T4.1
- **Acceptance:** S22 + S23 "Done when"; ACL matrix property tests; group-membership change effective without reindex; HNSW used in EXPLAIN.

#### T4.3 RRF fusion module (Cline → Claude)
- **Session:** S24 part: weighted Reciprocal Rank Fusion (`k0 = 60`, dense 0.55 / lexical 0.45), dedupe by chunk id, near-duplicate cap by `content_hash`, per-document cap preserving continuity
- **Depends on:** contract T1.0 (`RankedHit`)
- **Owned paths:** `app/rag/fusion/`
- **Acceptance:** pure functions; unit tests with hand-computed expected orders (weights, ties, missing branch, caps); 100% branch coverage of the module.

#### T4.4 Permission-aware hybrid search backend (Claude → Codex)
- **Session:** S24 (all except RRF, T4.3)
- **Depends on:** hard T4.2, T4.3
- **Acceptance:** S24 "Done when"; Hypothesis brute-force predicate comparison; restricted chunk never returned for exact-title queries; filtered HNSW recall ≥ 0.95 on the 5k fixture.

#### T4.5 Demo corpus file generator (Cline → Claude)
- **Session:** S25 part: `scripts/demo_corpus/` generates original synthetic documents from templates (reportlab / python-docx / openpyxl / python-pptx) into `evals/fixtures/corpus/demo/` + `manifest.json` (key, title, org, KB, classification, intended ACL, format)
- **Content (session.md S25):** Acme Corp HR KB (2025 and 2026 handbooks with a changed parental-leave policy, policy code **HR-142-B**, restricted compensation doc for the HR group), Support KB (manual, FAQ, troubleshooting), Engineering KB (runbooks, architecture notes with code), Compliance KB (numbered clauses across pages), one Spanish policy, one poisoned doc ("ignore previous instructions…"); Globex: deliberately similar handbook.
- **Depends on:** –
- **Owned paths:** `scripts/demo_corpus/`, `evals/fixtures/corpus/demo/`
- **Acceptance:** `make demo-corpus` regenerates deterministically; every format in plan §5.3 represented; no copyrighted text; manifest validated by a small test.

#### T4.6 Search API, demo seed loader, debug API (Claude → Codex)
- **Session:** S25 backend (search endpoints, query normalization, `query_runs`/`retrieval_hits`, `scripts/seed_demo.py` loading T4.5's corpus + orgs/users/memberships/groups) + S26 backend (`GET /v1/query-runs/{id}`, `debug=true`) + `tests/integration/test_gate_g4.py`
- **Depends on:** hard T4.4, T4.5
- **Acceptance:** S25/S26 backend "Done when"; retention off → no query text stored; G4 gate script green.

#### T4.7 Search UI + demo journeys (Cline → Claude)
- **Session:** S25 UI: instant search, facets, highlighted snippets, exact/semantic badges, keyboard navigation, preview in the evidence rail, "Ask about these results" link; Playwright **Demo 2/5/6** journeys
- **Depends on:** hard T2.5 · contract T4.6
- **Owned paths:** `apps/web/features/search/`
- **Acceptance:** S25 UI "Done when"; the three demo journeys green.

#### T4.8 Retrieval debugger UI (Codex → Claude)
- **Session:** S26 UI (all): pipeline stepper, results inspector, dense/lexical/fused toggles with keyed layout rank animation (off for reduced motion or > 50 rows), chunk preview, metadata panel, deep link; code-split from the employee bundle
- **Depends on:** hard T1.4 · contract T4.6
- **Owned paths:** `apps/web/features/debugger/`
- **Acceptance:** S26 UI "Done when"; rank-diff unit tests; admin sees both branches, member can't open it.

**G4** (Claude): §6 G4 + gate script + Cline QA → tag `gate-G4`.

### Sprint 5: grounded answers → G5

#### T5.1 Reranker, context packer & source aliases (Codex → Claude)
- **Session:** S27 library parts: `CrossEncoderReranker` (bge-reranker-v2-m3, ONNX/int8 on CPU, CUDA locally optional), `FakeReranker`, timeout + degraded signal, token-budget packer (per-doc cap, redundancy, neighbor-expansion **callback** supplied by the caller so authorization stays in Claude's search layer), `[S#]` alias builder; CPU latency report for 20/30 candidates
- **Depends on:** contract T1.0
- **Owned paths:** `app/providers/rerankers/`, `app/rag/context/`
- **Acceptance:** packer tests (budget, caps, expansion via callback); alias mapping stable; latency numbers written into agent.md I-003.

#### T5.2 LLM gateway, prompts, abstention & citation validator (Codex → Claude)
- **Session:** S28 library parts: `OpenAICompatibleLLM` (Ollama, Groq, Gemini, OpenRouter configs), gateway (Redis token bucket per provider, 429/`Retry-After`, bounded retries with jitter, fallback only to allowed models, usage capture), `FakeLLM` with scripted behaviours, prompt `configs/prompts/grounded_answer/v1.yaml` (untrusted-evidence delimiters, few-shot citations), abstention decision functions, citation validator (+ one bounded regeneration hook)
- **Depends on:** contract T1.0 (`LLMProvider`, RAG types)
- **Owned paths:** `app/providers/llm/`, `app/rag/generation/`, `app/rag/citations/`, `configs/prompts/`
- **Notes:** the prompt is security-relevant; Claude reviews it with extra care.
- **Acceptance:** validator tests (unknown, tampered, missing aliases; fail-safe); respx tests for 429 → fallback; `llm`-marked test against Ollama: poisoned evidence isn't obeyed.

#### T5.3 RAG profiles, model policies & `/query` orchestration (Claude → Codex)
- **Session:** S27 DB parts (`rag_profiles` immutable versions + `default-hybrid-v1`, `model_policies` base) + S28 orchestration (`POST /query`: normalize → search → rerank → pack → generate → validate; persist answers/citations/selected hits)
- **Depends on:** hard T4.6, T5.1, T5.2
- **Acceptance:** S27/S28 "Done when" (grounded answer with valid `[S#]` on the demo corpus via Ollama or Groq; abstains on an unanswerable question).

#### T5.4 SSE streaming, evidence status, conflicts + evidence endpoints (Claude → Codex)
- **Session:** S29 (all) + S31 backend: `GET /documents/{id}/versions/{vid}/content-url`, `GET /chunks/{id}/context`, `POST /query-runs/{id}/feedback` + `tests/integration/test_gate_g5.py`
- **Depends on:** hard T5.3
- **Acceptance:** S29 "Done when"; no open DB transaction during streaming (instrumented test); conflict fixture reported; G5 gate script green.

#### T5.5 Ask workspace UI (Codex → Claude)
- **Session:** S30 (all)
- **Depends on:** hard T1.4 · contract T5.4 (SSE schema from T1.0)
- **Owned paths:** `apps/web/features/ask/`, `apps/web/lib/events/`
- **Acceptance:** S30 "Done when"; stream reducer covers every event sequence; sanitizer tests; Playwright ask journey with `LLM_PROVIDER=fake`.

#### T5.6 Answer-state components, copy & feedback controls (Cline → Claude)
- **Session:** S31 parts: abstention card (§21.2 options), conflict card (§27.7.7), degraded banner, source-unavailable state, feedback buttons + reason codes, copy-answer formatters (plain / Markdown / with citations / section)
- **Depends on:** hard T1.4
- **Owned paths:** `apps/web/components/feedback/` (answer states), `apps/web/lib/copy-answer.ts`
- **Acceptance:** presentational + unit tests; showcased on `/dev/primitives` or a `/dev/answer-states` page; axe clean.

#### T5.7 Evidence rail, source viewer & feedback UI (Codex → Claude)
- **Session:** S31 UI (all except T5.6 components, which it integrates)
- **Depends on:** hard T5.5, T5.6, T3.7 (canonical renderer) · contract T5.4 endpoints
- **Owned paths:** `apps/web/features/evidence/`
- **Acceptance:** S31 "Done when"; Playwright citation → source for PDF and DOCX (**Demo 4**); keyboard-only citation navigation.

**G5** (Claude): §6 G5 + gate script + Cline QA → tag `gate-G5`. MVP core complete.

### Sprint 6: MVP deployment → M1

#### T6.1 Free-tier accounts & deployable backend image (Claude → Codex)
- **Session:** S32 (all). **The user** creates the free accounts and enters secrets; Claude guides and verifies.
- **Depends on:** hard G5
- **Acceptance:** S32 "Done when" (`make space-smoke` against real Neon/B2/Auth0/Groq).

#### T6.2 Staging smoke, Playwright smoke & keep-warm (Cline → Claude)
- **Session:** S33 parts: `scripts/smoke.py` (health, OIDC discovery, smoke-user token, upload, search, query with citation), Playwright staging project (login, search HR-142-B, ask with citation), optional daily keep-warm workflow
- **Depends on:** hard T1.7, T2.6 · contract T6.1
- **Owned paths:** `scripts/smoke.py`, `apps/web/tests/e2e/staging/`, `.github/workflows/keep-warm.yml` (Claude reviews workflow changes)
- **Acceptance:** runs green against the local stack (wave 8), then against staging once T6.1 deploys (wave 9).

#### T6.3 MVP staging deployment (Claude → Codex)
- **Session:** S33 (all except T6.2)
- **Depends on:** hard T6.1, T6.2 (local version)
- **Acceptance:** S33 "Done when" → **M1** tagged; README "Live demo" link; agent.md §4.8 filled.

---

## 5. Backlog after M1

Sessions 34–65 (session.md Sprints 7–16) are split into tasks after M1, using the same process: Claude designs and assigns in this file; the user approves.
