# ADR-008: Free-tier deployment topology

- **Status:** Accepted
- **Date:** 2026-10-12
- **Related:** plan.md §4.1, §38.2, §38.3; session.md §3; agent.md D-001 to D-006, DV-001 to DV-006

## Context

The project has **no budget**. plan.md §38.2 suggests Render/Railway-like compute, but (checked 2026-10-11) Render's free tier has no background workers and only 512 MB RAM, and Railway has no lasting free tier. The backend needs ~4+ GB RAM for Docling, OCR, ClamAV and in-process embedding/reranker models.

## Decision

| Concern | Deployed (free) |
|---|---|
| Web | Vercel Hobby |
| Backend processes | **One Hugging Face Docker Space** (CPU Basic: 2 vCPU / 16 GB / 50 GB ephemeral) running api, Celery workers, dispatcher, beat, Redis and clamd under **supervisord**. Staging = a second Space |
| Database | Neon Free (pgvector; `main` = production branch, `staging` branch) |
| Object storage | Backblaze B2 (S3 API, no card needed); Cloudflare R2 as drop-in alternative |
| Identity | Auth0 Free (Keycloak locally) |
| Models | In-process open embedding/reranker models; generation via Groq/Gemini free tiers (Ollama locally) |
| Observability | Grafana Cloud Free + Langfuse Cloud Hobby |
| CI/CD, registry | GitHub Actions + GHCR (public repo) |

**Same image, different commands.** `infra/docker/backend.Dockerfile` builds one backend image with `api` and `worker` targets; the Space image wraps it and starts every role under supervisord. On paid infrastructure (plan §38.3, the AWS reference module in Session 60) the same image runs each role as a separate service — no code changes.

## Consequences

- $0 hosting for the full product, including background processing.
- The Space sleeps after ~48 h without traffic and Neon scales to zero: cold starts are expected and documented.
- In-container Redis is ephemeral; acceptable because PostgreSQL is the source of truth (ADR-005).
- No persistent disk on free Spaces: model weights are baked into the image.
- The Space must be public; the application's own authentication protects data, and secrets live in Space secrets.
- Free cloud LLM tiers may retain prompts: only synthetic/demo data is used with them.

## Alternatives considered

- **Render/Railway** — rejected: no free workers / no lasting free tier.
- **Oracle Cloud Always Free VM** — rejected as default: requires a card and capacity is unreliable.
- **Self-hosting on the developer laptop with a tunnel** — rejected: availability.
