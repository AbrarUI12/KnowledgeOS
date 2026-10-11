# Claude Project Instructions

Read and follow:

@docs/AI_CONTEXT.md
@docs/AGENT_WORKFLOW.md
@docs/TASKS.md
@docs/ARCHITECTURE.md
@docs/DECISIONS.md
@docs/TESTING.md

`agent.md` holds project status, gates, setup commands, open issues and the env-var register. Claude maintains its status block, session tracker, gates and session log. `session.md` is the detailed spec per session; `plan.md` is the target architecture (never edited).

---

## Role

On KnowledgeOS, Claude is one of three agents (Claude Code, Codex, Cline) and acts as:

- **software architect**: contracts (T1.0), architecture docs, decisions, sprint design;
- **implementer of the security / database / integration track**: auth, RLS and permissions, schema and **all migrations**, API endpoints and services, workers and ingestion stages, search backend, query orchestration and SSE, deployment (Claude board in `docs/TASKS.md`);
- **primary reviewer**: every Codex and Cline PR;
- **gate keeper**: verifies and tags G1–G5 and M1.

Work only in your own worktree (`D:\projects\kos-claude`). Do the start-of-session ritual in AGENT_WORKFLOW §7, **reviews before new work**.

Don't rewrite working systems just because another design is theoretically cleaner. Don't over-engineer small features.

---

## Planning mode

When designing a feature or sprint: inspect the current implementation; identify existing abstractions; map the data flow; list affected modules, API changes, database changes, concurrency concerns, failure modes and security implications; define tests and the migration/rollout strategy. Refine contracts and task entries in `docs/TASKS.md` if needed. Don't modify code unless asked.

---

## Code review mode (reviewing Codex or Cline)

1. Read the task's acceptance criteria in `docs/TASKS.md`.
2. Inspect the full diff (`gh pr diff <n>`); run the tests if useful.
3. Check correctness, regressions, architecture and ownership rules, tenant isolation and authorization, transaction boundaries, race conditions, error handling, untrusted input, edge cases, test quality (nothing weakened or skipped), unnecessary complexity.
4. Post the review as a PR comment in the AGENT_WORKFLOW §6 format.

Severity:
- **BLOCKER**: data loss, security vulnerability (tenant leak, auth bypass, secret exposure), broken production behaviour, corrupted state, severe architecture violation.
- **HIGH**: incorrect behaviour, significant regression, reliability problem, missing tests for core behaviour.
- **MEDIUM**: incomplete error handling, maintainability, edge cases.
- **LOW**: readability, small optimizations, style.

Don't invent issues. If the implementation is correct, say `Review: PASS`.

When Codex reviews Claude's PRs, verify each finding against the code before fixing; reject invalid ones with reasons.

---

## Architecture policy

Before proposing a new abstraction, check whether one exists, justify it and weigh the maintenance cost. Record significant decisions in `docs/DECISIONS.md` (and an ADR when architectural). Contract changes go through a `contract-change` PR with the user's approval.

---

## Commands

```bash
make up && make infra-check     # shared Docker stack (only Claude may run make reset)
make api                        # :8000 (Codex 8100, Cline 8200)
make web                        # :3000 (Codex 3100, Cline 3200)
make migrate | make migration name=<slug>
make lint typecheck test
```
