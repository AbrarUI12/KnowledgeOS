# KnowledgeOS task runner.
# Windows: install GNU make (`winget install ezwinports.make`) and run from PowerShell or Git Bash.

API_DIR := apps/api
UV := uv --directory $(API_DIR)

COMPOSE := docker compose
# Per-agent dev ports (docs/AGENT_WORKFLOW.md §2): Claude 8000/3000, Codex 8100/3100, Cline 8200/3200
API_PORT ?= 8000
WEB_PORT ?= 3000

# openapi: regenerate packages/contracts/openapi.json (T1.0 contract)
.PHONY: openapi help install lint format typecheck test test-unit test-int migrate migration api web hooks env up up-full down reset logs ps psql infra-check demo-corpus worker dispatcher seed gate-g4 gate-g5 space-build space-run space-smoke

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

# ---------------------------------------------------------------- staging image (S32, fast-track C2)
SPACE_IMAGE ?= knowledgeos-space:local
SPACE_ENV ?= .env.staging

space-build: ## Build the all-in-one HF Space image (worker image first)
	docker build -f infra/docker/backend.Dockerfile --target worker -t knowledgeos-worker:local .
	docker build -f infra/docker/space.Dockerfile --build-arg BACKEND_IMAGE=knowledgeos-worker:local -t $(SPACE_IMAGE) .

space-run: ## Run the Space image locally against the real free-tier services ($(SPACE_ENV))
	docker run --rm --name kos-space -p 7860:7860 --env-file $(SPACE_ENV) $(SPACE_IMAGE)

space-smoke: ## Start the Space image detached and wait until /health/ready is green
	-docker rm -f kos-space >/dev/null 2>&1
	docker run -d --name kos-space -p 7860:7860 --env-file $(SPACE_ENV) $(SPACE_IMAGE)
	$(UV) run python ../../scripts/wait_ready.py http://localhost:7860 --timeout 600
