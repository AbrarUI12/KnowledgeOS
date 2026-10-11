# KnowledgeOS task runner.
# Windows: install GNU make (`winget install ezwinports.make`) and run from PowerShell or Git Bash.

API_DIR := apps/api
UV := uv --directory $(API_DIR)

.PHONY: help install lint format typecheck test api web hooks

help:
	@echo "install    Install backend (uv) and frontend (pnpm) dependencies + git hooks"
	@echo "lint       Ruff + ESLint + Prettier check"
	@echo "format     Auto-format backend and frontend"
	@echo "typecheck  mypy (strict) + tsc"
	@echo "test       pytest + vitest"
	@echo "api        Run the API with reload on http://localhost:8000"
	@echo "web        Run the Next.js dev server on http://localhost:3000"

install:
	$(UV) sync
	pnpm install --frozen-lockfile
	pre-commit install

lint:
	$(UV) run ruff check .
	$(UV) run ruff format --check .
	pnpm web:lint
	pnpm --filter @knowledgeos/web format:check

format:
	$(UV) run ruff format .
	$(UV) run ruff check --fix .
	pnpm --filter @knowledgeos/web format

typecheck:
	$(UV) run mypy
	pnpm web:typecheck

test:
	$(UV) run pytest
	pnpm web:test

api:
	$(UV) run uvicorn app.main:app --reload --port 8000

web:
	pnpm web:dev

hooks:
	pre-commit run --all-files
