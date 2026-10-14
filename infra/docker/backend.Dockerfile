# syntax=docker/dockerfile:1.7
#
# KnowledgeOS backend image. One image, several process roles (ADR-008):
#   docker build -f infra/docker/backend.Dockerfile --target api    -t knowledgeos-api .
#   docker build -f infra/docker/backend.Dockerfile --target worker -t knowledgeos-worker .
# Build context: repository root.

ARG PYTHON_VERSION=3.12

# ---------------------------------------------------------------- builder
FROM python:${PYTHON_VERSION}-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app

# Dependencies first (cached layer), then the project itself.
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project
COPY apps/api/app ./app
COPY apps/api/migrations ./migrations
COPY apps/api/alembic.ini ./
COPY configs/policies/content_scan.yaml ./configs/policies/content_scan.yaml
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------------------------------------------------------------- runtime base
FROM python:${PYTHON_VERSION}-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    ENVIRONMENT=production
# uid 1000: required by Hugging Face Spaces, harmless elsewhere.
RUN groupadd --gid 1000 app && useradd --uid 1000 --gid app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
USER app

# ---------------------------------------------------------------- api
FROM runtime AS api
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3).status == 200 else 1)"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

# ---------------------------------------------------------------- worker
# Celery worker (S16). Parser/OCR system packages are added with the real stages (T3.5).
# The dispatcher and beat run from this same image with a different command (docker-compose.yml).
FROM runtime AS worker
USER root
# OCR (Tesseract + English/Spanish for the demo corpus) and the GL/GLib libraries Docling's
# layout models need. Parsing runs only in workers, so the API image stays lean.
RUN apt-get update  && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa libgl1 libglib2.0-0  && rm -rf /var/lib/apt/lists/*
USER app
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel", "info", "--concurrency", "2", "-Q", "ingestion,sync,maintenance,eval,llm"]
