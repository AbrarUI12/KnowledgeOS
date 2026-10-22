# KnowledgeOS task runner.
# Windows: install GNU make (`winget install ezwinports.make`) and run from PowerShell or Git Bash.

API_DIR := apps/api
UV := uv --directory $(API_DIR)

COMPOSE := docker compose
# Per-agent dev ports (docs/AGENT_WORKFLOW.md §2): Claude 8000/3000, Codex 8100/3100, Cline 8200/3200
API_PORT ?= 8000
WEB_PORT ?= 3000

# openapi: regenerate packages/contracts/openapi.json (T1.0 contract)
.PHONY: openapi help install lint format typecheck test test-unit test-int migrate migration api web hooks env up up-full down reset logs ps psql infra-check demo-corpus worker dispatcher seed gate-g4 gate-g5

help:
	@echo "install    Install backend (uv) and frontend (pnpm) dependencies + git hooks"
	@echo "lint       Ruff + ESLint + Prettier check"
	@echo "format     Auto-format backend and frontend"
	@echo "typecheck  mypy (strict) + tsc"
	@echo "test       pytest (unit + integration, needs Docker) + vitest"
	@echo "test-unit  Backend unit tests only (no Docker)"
	@echo "test-int   Backend integration tests (Testcontainers)"
	@echo "migrate    Apply DB migrations to the local stack (alembic upgrade head)"
	@echo "migration  Create a migration: make migration name=add_users"
	@echo "api        Run the API with reload (API_PORT=8000 by default)"
	@echo "web        Run the Next.js dev server (WEB_PORT=3000 by default)"
	@echo "up         Start core local services (postgres, redis, minio, keycloak, mailpit)"
	@echo "up-full    Start core + clamav"
	@echo "down       Stop services (keeps data)"
	@echo "reset      Stop services and DELETE all local data volumes"
	@echo "infra-check  Verify every local service is healthy and configured"
	@echo "demo-corpus  Regenerate the demo corpus fixtures (T4.5)"

install:
	$(UV) sync
	pnpm install --frozen-lockfile
	pre-commit install

lint:
	$(UV) run ruff check . ../../scripts
	$(UV) run ruff format --check . ../../scripts
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

test-unit:
	$(UV) run pytest -m unit

test-int:
	$(UV) run pytest -m integration

migrate:
	$(UV) run alembic upgrade head

migration:
	@test -n "$(name)" || (echo "usage: make migration name=<slug>" && exit 1)
	$(UV) run alembic revision --autogenerate -m "$(name)"

openapi:
	$(UV) run python -m app.export_openapi

api:
	$(UV) run uvicorn app.main:app --reload --port $(API_PORT)

web:
	pnpm --filter @knowledgeos/web exec next dev --port $(WEB_PORT)

hooks:
	pre-commit run --all-files

env:
	@test -f .env || (cp .env.example .env && echo "created .env from .env.example")

up: env
	$(COMPOSE) up -d --wait
	$(COMPOSE) --profile init run --rm minio-init

up-full: env
	$(COMPOSE) --profile full up -d --wait
	$(COMPOSE) --profile init run --rm minio-init

down:
	$(COMPOSE) --profile full down

reset:
	$(COMPOSE) --profile full down -v

logs:
	$(COMPOSE) logs -f --tail=100

ps:
	$(COMPOSE) --profile full ps

psql:
	$(COMPOSE) exec postgres psql -U postgres -d knowledgeos

worker: ## Celery worker in Docker (prefork doesn't run on Windows)
	$(COMPOSE) --profile full up -d --build worker

dispatcher: ## outbox dispatcher in Docker
	$(COMPOSE) --profile full up -d --build dispatcher

seed: ## Seed the demo orgs, people, KBs and corpus through the running local API (S25)
	$(UV) run python ../../scripts/seed_demo.py --wait

gate-g4: ## Gate G4: full demo corpus with real parsers and Qwen3, searched through the API
	KOS_GATE=1 $(UV) run pytest -m gate tests/test_gate_g4.py -v

gate-g5: ## Gate G5: grounded answers over the demo corpus (KOS_GATE_LLM=ollama|groq)
	KOS_GATE=1 KOS_GATE_LLM=$(or $(KOS_GATE_LLM),ollama) $(UV) run pytest -m gate tests/test_gate_g5.py -v

demo-corpus:
	$(UV) run python ../../scripts/demo_corpus/generate.py

infra-check:
	$(UV) run python ../../scripts/check_infra.py
