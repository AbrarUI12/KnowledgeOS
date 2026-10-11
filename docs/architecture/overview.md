# Architecture overview

KnowledgeOS is a **modular monolith** (ADR-001): one FastAPI backend plus Celery workers sharing one codebase and one PostgreSQL database, and a Next.js frontend. Full specification: [`plan.md`](../../plan.md).

## System view

```mermaid
flowchart TB
    U[Browser / API client] --> W[Next.js web app]
    U -->|bearer token, SSE| A[FastAPI API]
    W --> IDP[OIDC provider<br/>Keycloak / Auth0]
    A -->|JWKS| IDP

    A --> PG[(PostgreSQL + pgvector<br/>RLS on every tenant table)]
    A --> R[(Redis)]
    A --> OBJ[(S3-compatible storage<br/>quarantine / trusted / artifacts)]
    U -->|presigned PUT| OBJ

    A -->|same transaction| OUT[outbox_events]
    OUT --> D[Dispatcher]
    D --> Q[Celery queues]
    Q --> IW[Workers]
    IW --> AV[ClamAV]
    IW --> PARSE[Docling / OCR]
    IW --> EMB[Embedding model]
    IW --> PG
    IW --> OBJ

    A --> QS[Query pipeline]
    QS --> HYB[Permission-aware hybrid search]
    HYB --> PG
    HYB --> RR[Reranker]
    RR --> CTX[Context packing]
    CTX --> LLM[LLM gateway<br/>Ollama / Groq / Gemini]
    LLM --> CV[Citation validation]
    CV -->|SSE| U

    A --> OBS[Traces / metrics<br/>OTel, Langfuse]
    IW --> OBS
```

## Request path rules

1. Authenticate (OIDC JWT) → resolve organization membership → set transaction-local tenant context (ADR-003, ADR-004).
2. Authorize **before** any retrieved content reaches a model; authorization filters are part of the retrieval SQL (ADR-002).
3. Retrieved content is untrusted data, delimited as evidence, never instructions.
4. Providers are reached only through policy-checked interfaces (ADR-006).
5. No DB transaction stays open while an LLM streams.

## Deployment views

### Local development (Docker Compose)

```mermaid
flowchart LR
    subgraph Host[Developer machine]
        WEB[next dev :3000]
        API[uvicorn :8000]
    end
    subgraph Compose[docker compose]
        PG[(pgvector pg17 :5433)]
        RD[(redis :6380)]
        MN[(MinIO :9000/9001)]
        KC[Keycloak :8080]
        MP[Mailpit :8025]
        CV[ClamAV :3310 · full profile]
        WK[Celery workers · full profile, Session 16]
    end
    WEB --> API
    WEB --> KC
    API --> PG & RD & MN & KC
    WK --> PG & RD & MN & CV
```

### Free-tier deployment (ADR-008)

```mermaid
flowchart LR
    B[Browser] --> V[Vercel · Next.js]
    B --> S
    V --> A0[Auth0]
    subgraph S[Hugging Face Docker Space · supervisord]
        API[api] --- WRK[workers] --- DSP[dispatcher] --- BT[beat] --- RDS[(redis)] --- CLM[clamd]
    end
    S --> N[(Neon Postgres + pgvector)]
    S --> B2[(Backblaze B2)]
    S --> G[Groq / Gemini free tiers]
    S --> O[Grafana Cloud · Langfuse]
    B -->|presigned PUT| B2
```

### Enterprise reference (documented, not deployed)

The same backend image runs each role as a separate service (ECS/Kubernetes), with managed PostgreSQL, Redis, S3, KMS, WAF and private networking — see plan.md §38.3 and the Terraform reference module (Session 60).
