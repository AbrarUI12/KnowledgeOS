# Multi-Agent Workflow: Claude Code + Codex + Cline

> How three coding agents build KnowledgeOS **at the same time** without overwriting each other, duplicating work or drifting from the architecture. Task assignments and status live in [`docs/TASKS.md`](TASKS.md). Shared project knowledge lives in [`docs/AI_CONTEXT.md`](AI_CONTEXT.md).

---

## 1. Roles

| Agent | Role | Owns (typical work) | Reviews |
|---|---|---|---|
| **Claude** (Claude Code) | Architect, security and integration engineer, primary reviewer | contracts and architecture docs; auth, RLS and permissions; database schema and **all migrations**; API endpoints and services; workers and ingestion stages; search backend; query orchestration and SSE; deployment; gate verification | every Codex and Cline PR |
| **Codex** | Primary library and frontend engineer | providers (storage, scanning, embeddings, reranker, LLM), file validation, parsing/normalization/chunking, context packing and citation validation; frontend foundation (auth, typed client, shell), Ask experience, evidence rail, retrieval debugger | every Claude PR |
| **Cline** | IDE pair programmer | contained UI pages (access, knowledge library, ingestion, search), presentational components, Playwright harness and journeys, dev scripts, demo corpus, RRF module, local QA passes at each gate | – (its PRs are reviewed by Claude) |
| **You** (the user) | Tech lead | priorities, architecture and contract approvals, account and secret setup, final say on any disagreement | as you like |

Approximate split up to M1: Claude ≈ 42%, Codex ≈ 43%, Cline ≈ 15%.

**Never assign the same task to two agents.** One task, one owner, one branch, one PR.

---

## 2. Workspaces (git worktrees)

**Never let two agents edit the same working tree.** Each agent has its own folder on its own branch. All folders share one `.git`.

| Folder | Who | Notes |
|---|---|---|
| `D:\projects\KnowledgeOS` | you (integration checkout) | stays on `main`; pull to see the current state |
| `D:\projects\kos-claude` | Claude | |
| `D:\projects\kos-codex` | Codex | |
| `D:\projects\kos-cline` | Cline | open this folder in VS Code for Cline |

Short paths are deliberate (Windows MAX_PATH, agent.md I-004). Each worktree needs its own `.env` (copy from the integration checkout) and its own `make install`.

Create a new task branch inside your own worktree:
```bash
git fetch origin
git switch -c ai/<agent>-<task-id>-<slug> origin/main     # e.g. ai/codex-t2.3-file-validation
```

### Local ports (run dev servers side by side)

| Agent | API | Web |
|---|---|---|
| Claude | `make api` (8000) | `make web` (3000) |
| Codex | `make api API_PORT=8100` | `make web WEB_PORT=3100` |
| Cline | `make api API_PORT=8200` | `make web WEB_PORT=3200` |

Keycloak and MinIO accept all three web origins. When running the web app on 3100/3200, set `AUTH_URL=http://localhost:<port>` in that worktree's environment (Session 10 adds the variable).

### Shared Docker stack

There is **one** Compose stack (project `knowledgeos`). Anyone may `make up` / `make up-full` (idempotent). **Only Claude runs `make reset` or `docker compose down -v`**, and only after posting in an `agent-question` issue first, because it wipes everyone's local data. Automated tests use Testcontainers and never touch this stack.

---

## 3. Branches, commits and PRs

- Branch: `ai/<claude|codex|cline>-<task-id>-<slug>`, always from `origin/main`.
- Commits: small, Conventional Commits with the task ID, e.g. `feat(storage): add S3 object store (T2.2)`.
- Open a **draft PR early** (title `[T2.2] S3/MinIO ObjectStore providers`) using the PR template. It signals what's in flight.
- Before marking ready: `git fetch && git merge origin/main`, then `make lint typecheck test`.
- One task per PR. Never implement adjacent tasks "while you're there". Note them under follow-ups instead.

---

## 4. File ownership

Edit files you own. If your task needs a change in someone else's area, ask on an `agent-question` issue or include the smallest possible change and call it out in the PR for that owner's review.

| Area | Owner |
|---|---|
| `apps/api/app/{auth,api,db,services,workers,domain}/` | Claude |
| `apps/api/migrations/` + `app/db/models/` + `app/db/models/__init__.py` | **Claude only** |
| `apps/api/app/api/v1/router.py` (router registration) | **Claude only** |
| `app/ingestion/stages/`, `app/rag/retrieval/`, `app/rag/orchestration/`, `app/providers/{search,identity}/` | Claude |
| Contract files from T1.0 (`app/providers/*/base.py`, `app/ingestion/canonical.py`, `app/ingestion/chunking/types.py`, `app/ingestion/parsing/base.py`, `app/security/content_types.py`, `app/rag/types.py`, `app/domain/enums.py`, `app/domain/schemas/`, `packages/contracts/openapi.json`, `tests/fakes/`, `docs/api/sse-events.md`) | Claude (changes = `contract-change` PR) |
| `infra/`, `docker-compose.yml`, `.github/workflows/`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md` | Claude |
| `app/providers/{storage,scanning,embeddings,rerankers,llm}/` (implementations) | Codex |
| `app/security/{file_validation,content_scanner}.py`, `app/ingestion/{parsing,normalize,chunking}/` (implementations) | Codex |
| `app/rag/{context,citations,generation}/`, `configs/prompts/` | Codex |
| `apps/web/lib/{api,auth,events}/`, `apps/web/components/shell/`, `apps/web/features/{ask,evidence,debugger}/`, `packages/contracts/` | Codex |
| `apps/web/features/{access,knowledge,documents,ingestion,search}/`, `apps/web/components/{command,feedback}/` | Cline |
| `apps/web/tests/e2e/`, `apps/web/playwright.config.ts` | Cline |
| `app/rag/fusion/`, `scripts/demo_corpus/`, `scripts/{get_token,upload_file,smoke}.py` | Cline |
| `apps/web/components/primitives/`, `styles/`, `lib/motion/` (design system) | Claude (others may extend with a reviewed PR) |
| **Shared:** `apps/api/pyproject.toml`, `apps/web/package.json`, `Makefile`, `README.md`, `agent.md`, `docs/TASKS.md` | everyone, minimal edits, see §8 |

**Lockfiles** (`uv.lock`, `pnpm-lock.yaml`) are never hand-merged. On conflict: take `origin/main`'s version, then re-run `uv lock` / `pnpm install` with your added dependency.

**Database rule:** Codex and Cline write DB-free code (Pydantic/dataclasses in, out). If your task needs a table or column, put the spec in your PR or in a `blocker` issue to `[to:claude]`; Claude adds the migration. This prevents competing Alembic heads.

---

## 5. Contract-first development

Claude's first task (T1.0) publishes the interfaces everyone codes against:
- provider Protocols: ObjectStore, MalwareScanner (T2.3's API), DocumentParser, ContentScanner, Chunker, EmbeddingProvider, RerankerProvider, LLMProvider, SearchBackend;
- core models: `CanonicalDocument`, `ChunkDraft`, RAG types (`Candidate`, `RankedHit`, `EvidenceItem`, `SourceAlias`);
- Pydantic API schemas for me/orgs/members/groups/KBs/documents/uploads/jobs/search/query/debug, so the OpenAPI spec and the generated TS client exist before the endpoints do;
- the SSE event schema (`docs/api/sse-events.md`).

Tasks marked **contract** dependency in TASKS.md build against these with fakes or mocks and finish integration once the provider merges. **Changing a contract** needs a PR labelled `contract-change`, approval from the user, and a note to affected agents.

---

## 6. Review loop and merge rule

```text
author implements ─► tests green ─► PR ready ─► cross-agent review ─► author verifies each finding
      ─► fixes valid ones, rejects invalid ones with reasons ─► CI green ─► author merges (if no open BLOCKER/HIGH)
```

| Author | Reviewer |
|---|---|
| Codex | Claude |
| Cline | Claude |
| Claude | Codex |

- Reviews are **PR comments** (`gh pr comment <n> --body-file review.md`). All agents share one GitHub account, so formal approvals aren't possible.
- Every review ends with one status line: `Review: PASS` or `Review: CHANGES REQUESTED (BLOCKER n, HIGH n)`.
- **Merge rule:** the author merges (`gh pr merge <n> --merge --delete-branch`) when CI is green **and** the latest review says PASS, or lists only MEDIUM/LOW items (fixed or ticketed as follow-ups).
- **Needs the user's OK before merging:** `contract-change` PRs, changes to `docs/ARCHITECTURE.md` or `docs/DECISIONS.md`, new ADRs, anything touching deployment secrets, and any disagreement between author and reviewer about a BLOCKER/HIGH.
- If a review hasn't arrived within the reviewer's next work session, the author pings on the PR with `[to:claude] please review` / `[to:codex] please review`.
- Dependabot PRs are handled by the user.

### Review format

```markdown
## Review of #<PR> (<task id>) by <agent>

### BLOCKER
- `path/file.py:L42`: problem → impact → recommended fix

### HIGH
### MEDIUM
### LOW
(write "none" for empty sections)

Review: PASS | CHANGES REQUESTED (BLOCKER n, HIGH n)
```

Severity guide:
- **BLOCKER**: data loss, security hole (tenant leak, auth bypass, secret exposure), broken production behaviour, corrupted state, severe architecture violation.
- **HIGH**: incorrect behaviour, significant regression, reliability problem, missing tests for core behaviour.
- **MEDIUM**: incomplete error handling, maintainability, edge cases.
- **LOW**: readability, small optimizations, style.

Don't invent issues to have something to say. If it's correct, say PASS.

---

## 7. Communication protocol

> **Addressing:** write `[to:claude]`, `[to:codex]` or `[to:cline]` at the start of a comment or issue. **Never write `@codex` (or `@claude`) on GitHub**: those mentions summon the vendors' cloud bots (OpenAI's Codex connector answered our first `@codex`). All agents share one GitHub account, so `@`-mentions can't reach an agent anyway.

1. **Files are the long-term memory:** `docs/AI_CONTEXT.md` (context), `docs/ARCHITECTURE.md` (structure), `docs/DECISIONS.md` (why), `docs/TESTING.md` (how to test), `docs/TASKS.md` (who does what, status).
2. **PRs carry the work:** draft PR = claim; PR description = completion report; PR comments = reviews and replies.
3. **GitHub Issues carry questions and blockers only.** Labels `agent-question` or `blocker`. Open with the addressee tag: `[to:codex] is ChunkDraft.page_end inclusive?` Close when answered; if the answer changes a contract or decision, record it in the right doc.
4. **agent.md Team status** shows each agent's current task, last finished task and blockers at a glance.
5. **Never rely on chat memory.** Every handoff points to files, commits or PRs: "Implement T4.3. Contract: `app/rag/types.py`. Previous work: PR #21."

### Start-of-session ritual (every agent, every time)

```bash
git fetch origin && git merge origin/main                         # in your worktree
gh pr list --state open --search "<you> in:comments"     # e.g. "codex in:comments"; read the [to:<you>] comments
gh issue list --label agent-question --state open
gh issue list --label blocker --state open
```
Then read your block in `agent.md` → Team status and your next task in `docs/TASKS.md`, and do **reviews before new work**: a waiting review blocks another agent.

### End-of-task ritual

1. `make lint typecheck test` green; PR description filled (completion report).
2. In `docs/TASKS.md`: your task's Status, PR and, after merge, Commit.
3. In `agent.md`: your Team status block (current/last task, 1–3 line summary, PR link) and, if you introduced them, env-var names (§11) and open issues (§8).
4. New decision? Add a row to `docs/DECISIONS.md` (or flag it for Claude if it's architectural).

---

## 8. Editing shared files without conflicts

- **`docs/TASKS.md`**: edit only the entries of tasks you own (status, branch, PR, commit). Don't reorder or reformat.
- **`agent.md`**: edit only your own Team status block, and add your own rows to open issues and env-var register. Claude maintains the status block (§1), the session tracker, gates and the session log.
- **`Makefile` / `pyproject.toml` / `package.json`**: smallest possible addition, in your task's PR, mentioned in the PR description.
- Conflicts in these files are usually trivial: merge `origin/main` in, keep both sides, re-run checks.

---

## 9. Ready-made prompts

Paste these into the agent, replacing the placeholders.

### Start a task (Codex or Cline)
```text
Read AGENTS.md (Codex) or .clinerules (Cline), then docs/AI_CONTEXT.md, docs/AGENT_WORKFLOW.md and
the entry for <TASK ID> in docs/TASKS.md, then the session.md section it references and the plan.md
sections that session cites. Do the start-of-session ritual from AGENT_WORKFLOW §7 (reviews first).
Then implement <TASK ID> only, in my worktree on a new branch ai/<agent>-<task-id>-<slug> from
origin/main. Stay inside the task's owned paths. Code against the T1.0 contracts. Write tests with
the code. Open a draft PR early using the PR template. When done: make lint typecheck test,
update docs/TASKS.md and your agent.md Team block, mark the PR ready and request review from the
reviewer listed in the task.
```

### Claude: plan / design a sprint
```text
Read docs/AI_CONTEXT.md, docs/ARCHITECTURE.md, docs/DECISIONS.md and the session.md sections for
sprint <N>. Inspect the existing code. Do not modify code yet. Produce: affected modules, data flow,
API changes, database changes, transaction boundaries, failure modes, security implications, tests.
Update the contracts and the task entries in docs/TASKS.md if they need refinement.
```

### Review a PR (Claude reviewing Codex/Cline, Codex reviewing Claude)
```text
Review PR #<n> (<TASK ID>). Do NOT change code. Read docs/AI_CONTEXT.md, docs/ARCHITECTURE.md,
docs/TASKS.md (acceptance criteria for <TASK ID>) and docs/DECISIONS.md. Inspect the full diff
(gh pr diff <n>) and run the tests locally if useful. Check: correctness vs acceptance criteria,
tenant isolation and authorization, transaction boundaries, race conditions, error handling,
untrusted-input handling, edge cases, test quality (no weakened or skipped tests), unnecessary
complexity, scope creep outside owned paths. Post the review with the format in AGENT_WORKFLOW §6.
Do not invent issues.
```

### Address a review
```text
Read the review on PR #<n>. For every BLOCKER and HIGH (and MEDIUM where cheap): verify it against
the actual code; fix it only if valid; if invalid, explain why. Don't follow the review blindly.
Re-run make lint typecheck test. Reply on the PR with a list: finding → fixed (commit) / rejected
(reason). Merge per AGENT_WORKFLOW §6 when allowed.
```

### Debug (Cline's specialty)
```text
Problem: <observed behaviour>. Expected: <expected>. Read docs/AI_CONTEXT.md and the relevant task in
docs/TASKS.md. Don't redesign. Reproduce or trace the problem, identify and explain the root cause,
apply the smallest safe fix, add a regression test if practical, run the relevant tests.
```

### Local QA pass at a gate (Cline)
```text
Gate <G#> QA. Pull main into your worktree, make install, make up, make migrate, start API (8200) and
web (3200). Walk through every acceptance criterion of the gate in session.md §6 and the Playwright
journeys. Fix only small TS/runtime/UI issues in your own areas. For anything else open a `blocker`
issue to the owner. Post a QA report as a comment on the gate's tracking PR or issue.
```

---

## 10. Model and effort guidance

Use the strongest model and high effort for architecture, contracts, security (auth, RLS, ACL predicates, injection handling), concurrency and transactions, and reviews of those areas. Use faster settings for UI layout and CSS, docs, simple CRUD, fixtures, renames and repetitive tests. Don't spend maximum reasoning on everything.

## 11. Ten core rules

1. Never share a working tree; one worktree and branch per agent.
2. Shared knowledge lives in files, not chat history.
3. One task, one owner, one PR. Never implement a task assigned to someone else.
4. Code against the published contracts; change them only via `contract-change`.
5. Only Claude writes migrations and registers routers.
6. Tests with every change; never weaken or skip tests.
7. Every PR is reviewed by another agent; verify findings before fixing.
8. Merge only on green CI and no open BLOCKER/HIGH.
9. Reviews before new work.
10. The user decides on architecture, contracts and disagreements.
