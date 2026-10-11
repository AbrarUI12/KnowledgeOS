# Cline Project Rules: KnowledgeOS

You are one of three coding agents on KnowledgeOS (Claude Code, Codex, Cline). Cline's role is **IDE pair programmer**: contained UI pages, presentational components, Playwright tests, dev scripts, the demo corpus, the RRF module, local QA passes, and small targeted fixes. Your PRs are reviewed by Claude.

## Always read first

1. `docs/AI_CONTEXT.md`: context, stack, rules, commands, definition of done
2. `docs/AGENT_WORKFLOW.md`: worktrees, branches, file ownership, review and merge rules, communication
3. `docs/TASKS.md`: your board is **Cline**; read your task's spec and the referenced `session.md` section
4. For frontend work: `docs/architecture/frontend-design.md` and `apps/web/AGENTS.md` (Next.js 16: check `apps/web/node_modules/next/dist/docs/`)

## Workspace

- Work **only** in `D:\projects\kos-cline` (open that folder in VS Code), on a branch `ai/cline-<task-id>-<slug>` created from `origin/main`.
- Dev servers: `make api API_PORT=8200`, `make web WEB_PORT=3200`. Never run `make reset` (it wipes the shared stack).
- Start of session: `git fetch origin && git merge origin/main`, then check `gh issue list --label agent-question` and your open PRs for review comments.

## Development rules

1. Work on **one task** at a time; implement only that task.
2. Stay in your owned paths: `apps/web/features/{access,knowledge,documents,ingestion,search}/`, `apps/web/components/{command,feedback}/`, `apps/web/tests/e2e/`, `app/rag/fusion/`, `scripts/demo_corpus/`, `scripts/{get_token,upload_file,smoke}.py`.
3. Use the **generated API client** (`apps/web/lib/api`) and the design-system primitives (`components/primitives`). Never use raw colors (lint fails); use tokens.
4. Don't refactor unrelated code. Prefer the smallest safe change. Preserve the architecture.
5. Don't introduce dependencies for trivial functionality. Don't silently modify configuration files (`Makefile`, `package.json`, CI); mention any change in the PR.
6. Never write database models, migrations or backend routes. Those belong to Claude; ask in a `blocker` issue.
7. Every page needs loading, empty and error states, keyboard access and responsive layout. Run axe in tests.
8. Run `pnpm web:lint`, `pnpm web:typecheck`, `pnpm web:test` (and Playwright where relevant) before marking a PR ready.

## Debugging rules

1. Reproduce the failure. 2. Read logs/errors. 3. Find the root cause and explain it before fixing anything non-trivial. 4. Avoid symptom-only fixes. 5. Apply the smallest safe correction. 6. Add a regression test if practical. 7. Verify the original failure is gone.

## Finishing a task

1. Checks green; PR from the template with the completion report (changed / tests / risks).
2. Update **your rows only** in `docs/TASKS.md` and **your block only** in `agent.md` → Team status.
3. Mark the PR ready and comment `[to:claude] please review`.
4. Address the review: verify each finding, fix valid ones, explain rejected ones.
5. Merge (`gh pr merge <n> --merge --delete-branch`) only when CI is green and the review says PASS (or only MEDIUM/LOW handled).
