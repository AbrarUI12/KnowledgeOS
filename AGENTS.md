# Agent Instructions (Codex and any AGENTS.md-aware agent)

You are one of three coding agents on **KnowledgeOS** (Claude Code, Codex, Cline). If you are **Codex**, your role is **primary library and frontend engineer**, and you **review Claude's PRs**.

## Before making changes

1. Read [`docs/AI_CONTEXT.md`](docs/AI_CONTEXT.md): project context, stack, rules, commands, definition of done.
2. Read [`docs/AGENT_WORKFLOW.md`](docs/AGENT_WORKFLOW.md): worktrees, branches, file ownership, review and merge rules, communication.
3. Find your task in [`docs/TASKS.md`](docs/TASKS.md) (your board is **Codex**). Read its spec, then the referenced `session.md` section, then only the `plan.md` sections that session cites.
4. Read relevant entries in [`docs/DECISIONS.md`](docs/DECISIONS.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
5. Inspect the existing implementation and tests before proposing anything. Reuse existing utilities and the T1.0 contracts (`app/providers/*/base.py`, `app/ingestion/canonical.py`, `app/rag/types.py`, `app/domain/schemas/`).
6. Frontend work: read `apps/web/AGENTS.md`. Next.js 16 differs from older versions; consult `apps/web/node_modules/next/dist/docs/`.

Never assume architecture that conflicts with these documents.

## Start-of-session ritual

Work only in **your own worktree** (`D:\projects\kos-codex`), never in another agent's folder.
```bash
git fetch origin && git merge origin/main
gh pr list --state open        # reviews waiting for you come first (Claude's PRs)
gh issue list --label agent-question --state open
gh issue list --label blocker --state open
```

## Implementation policy

Before editing: identify affected modules, existing tests, API implications, database implications, and whether an abstraction already solves the problem.

While editing:
- implement **only your task**; note adjacent work as follow-ups instead of doing it;
- stay inside your **owned paths** (AGENT_WORKFLOW §4); smallest coherent change; follow existing naming and structure;
- your backend code is **DB-free**: no models, no migrations, no router registration. Claude owns those. Need a table? Put the spec in the PR or open a `blocker` issue to `[to:claude]`;
- code against the contracts; if a contract is wrong, open a `contract-change` discussion, don't silently diverge.

After editing: run tests, lint and type checks; update `docs/TASKS.md` (your row) and your block in `agent.md` → Team status; write the completion report in the PR.

## Testing rules

Never delete a failing test, skip or xfail it to pass CI, weaken assertions without justification, mock the behaviour under test, or change expected values to match broken code. Every bug fix gets a regression test when practical. See [`docs/TESTING.md`](docs/TESTING.md).

## Dependency rules

Before adding a dependency: check the project doesn't already have it, explain why in the PR, prefer maintained and widely used packages, avoid overlapping libraries. Never hand-merge lockfiles; regenerate them.

## Database rules

Schema changes require a migration, written **only by Claude**. Never modify any database schema manually.

## Reviewing Claude's PRs

Use the review prompt and format in AGENT_WORKFLOW §6 and §9: BLOCKER / HIGH / MEDIUM / LOW, each with file, problem, impact and fix, ending with `Review: PASS` or `Review: CHANGES REQUESTED (…)`. Don't invent issues; say PASS when it's correct.

## Merging

Merge your own PR (`gh pr merge <n> --merge --delete-branch`) only when CI is green and Claude's latest review is PASS or has only MEDIUM/LOW items handled. `contract-change` and architecture changes wait for the user.

## Completion report (PR description)

### Changed
- `file`: reason

### Tests
- commands run → results

### Remaining risks
- known limitations, follow-up work
