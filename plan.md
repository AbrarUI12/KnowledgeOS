# KnowledgeOS — Enterprise / Business-Grade RAG Platform

**Document:** Master Implementation Plan  
**Status:** Final architecture after iterative design review  
**Primary objective:** Build a production-style, multi-tenant Retrieval-Augmented Generation platform that can ingest company knowledge, preserve document permissions, retrieve evidence with hybrid search and reranking, generate grounded answers with verifiable citations, support cloud/local models, and expose evaluation, observability, security, and administration features expected from a real business system.

---

## 1. Product definition

KnowledgeOS is a multi-tenant enterprise knowledge platform. Organizations create isolated workspaces, connect or upload internal knowledge, invite users and groups, assign permissions, and query that knowledge through a grounded AI assistant.

The project is intentionally **not** a “chat with PDF” demo. The product must demonstrate the complete RAG lifecycle:

1. authenticated user and tenant context;
2. secure document acquisition;
3. provenance and versioning;
4. parsing/OCR/normalization;
5. structure-aware chunking;
6. dense and lexical indexing;
7. permission-aware retrieval;
8. hybrid fusion and reranking;
9. evidence selection and context construction;
10. grounded generation;
11. citation validation;
12. feedback collection;
13. offline and online evaluation;
14. tracing and cost analytics;
15. reliable re-indexing, deletion and permission propagation;
16. security controls and auditability;
17. production deployment and CI/CD.

### 1.1 Primary users

- **Organization owner:** manages the organization, billing-level settings, identity integrations, model policy, retention policy and administrators.
- **Administrator:** manages knowledge bases, data sources, members, groups, documents, retrieval profiles, evaluation and audit logs.
- **Knowledge manager/editor:** uploads, approves, replaces, tags and retires documents.
- **Employee/member:** searches and chats only against content they are permitted to access.
- **Viewer:** read/query access with no content-management privileges.
- **API client/service account:** programmatic retrieval or RAG access with narrowly scoped API keys.

### 1.2 Core business scenarios

The finished system must support at least these scenarios:

- HR assistant over employee policy documents.
- Support assistant over product manuals, FAQs and troubleshooting documents.
- Engineering knowledge assistant over runbooks, architecture notes and technical documentation.
- Compliance/policy search with exact clause and page citations.
- Cross-document comparison such as “How did the leave policy change between 2025 and 2026?”
- Department-restricted documents where unauthorized users never retrieve restricted chunks.
- Local-only knowledge bases where document content is never sent to an external LLM/embedding provider.
- Versioned knowledge where an outdated document can be replaced and removed from active retrieval without destroying its audit history.

---

## 2. Success criteria and non-goals

### 2.1 Product success criteria

The project is considered business-grade only when all of the following are true:

- Tenant A cannot retrieve, infer or receive Tenant B content.
- Access is checked **before retrieved content reaches the generation model**.
- Every normal business answer is source-grounded and exposes verifiable citations.
- Unsupported questions can abstain rather than hallucinate an answer.
- Exact identifiers and semantic paraphrases both retrieve well.
- Upload, replacement, deletion and permission changes propagate to the searchable index.
- RAG quality can be measured against a versioned evaluation set.
- Every query has a trace showing retrieval, reranking, model, latency and usage metadata.
- Admins can identify why a poor answer occurred.
- Cloud and local model providers are replaceable through provider interfaces.
- Ingestion is asynchronous, idempotent and recoverable after worker failure.
- Security tests cover prompt injection, cross-tenant leakage, stale permissions, malicious files, cache leakage and deletion propagation.
- The deployment can be reproduced from source using containers and infrastructure configuration.

### 2.2 Reference quality gates

These are project targets and must be calibrated on the final evaluation corpus rather than treated as universal constants:

- Cross-tenant retrieval leakage: **0 accepted failures**.
- Unauthorized within-tenant retrieval: **0 accepted failures**.
- Retrieval Recall@10: target **>= 0.90** on the curated fact-retrieval subset.
- Citation validity: target **>= 0.98** for citation identifiers pointing to real selected sources.
- Citation support/precision: target **>= 0.90** on reviewed evaluation cases.
- Faithfulness/groundedness: target **>= 0.90** on the curated evaluation set.
- Correct abstention on unanswerable cases: target **>= 0.90**.
- Retrieval P95 latency: target **< 500 ms** at the reference data scale, excluding external model generation.
- End-to-end P95: initial target **< 6 s**, provider dependent.
- No critical/high unresolved findings in the project threat-model test suite before production promotion.

### 2.3 Non-goals for the first production release

Do **not** add these until the core RAG system passes its gates:

- autonomous agents that execute business actions;
- arbitrary tool calling from retrieved content;
- fine-tuning foundation models;
- an unrestricted SQL agent;
- real financial or payment processing;
- SOC 2 / HIPAA / ISO certification claims;
- global hyperscale architecture;
- fully general multimodal reasoning over video/audio;
- replacing enterprise source systems as the source of truth.

The architecture may prepare for these, but they must not distract from the core retrieval system.

---

## 3. Architectural principles

1. **Modular monolith first.** One FastAPI backend plus workers, not premature microservices.
2. **Tenant isolation from day one.** Do not retrofit `organization_id` later.
3. **Authorization before generation.** The LLM is never the security boundary.
4. **Retrieved content is untrusted data.** It can contain malicious instructions.
5. **Provider-neutral core.** LLM, embeddings, reranker, object storage, identity and search sit behind interfaces.
6. **PostgreSQL-first, search-backend portable.** Begin with PostgreSQL full-text search + pgvector; move to OpenSearch/Qdrant/Weaviate/Vespa only when measured scale or features justify it.
7. **Immutable versions.** Documents, RAG profiles, prompts and index generations are versioned for reproducibility.
8. **Evaluation-gated changes.** Chunking, embedding, retrieval, reranking and prompts cannot silently change production behavior.
9. **Fail closed for security.** If authorization cannot be established, return no data.
10. **No silent embedding fallback.** An embedding model change requires a new index generation/re-embedding.
11. **Async ingestion.** HTTP requests enqueue work; they never parse/embed large documents synchronously.
12. **Observability is a feature.** A production AI system that cannot explain its retrieval path is unfinished.
13. **Privacy-aware defaults.** Query/content logging is configurable and minimized.
14. **Explicit degradation.** Vector-only, lexical-only or reranker-bypassed operation is marked in traces and responses where relevant.

---

## 4. Reference architecture

```mermaid
flowchart TB
    U[Browser / API Client] --> W[Next.js Web App]
    W --> A[FastAPI API]

    A --> IDP[OIDC Identity Provider]
    A --> PG[(PostgreSQL + pgvector)]
    A --> R[(Redis)]
    A --> OBJ[(S3/R2/MinIO Object Storage)]
    A --> LLM[LLM Gateway]
    A --> EMB[Embedding Gateway]
    A --> RR[Reranker Gateway]
    A --> OBS[Tracing / Evaluation]

    W -->|direct presigned upload| Q[(Quarantine Object Bucket)]
    A --> OUT[Transactional Outbox]
    OUT --> D[Outbox Dispatcher]
    D --> QW[Job Queue]
    QW --> IW[Ingestion Workers]

    IW --> Q
    IW --> AV[Malware / file validation]
    AV --> PARSE[Docling / parsers / OCR]
    PARSE --> CAN[Canonical document artifact]
    CAN --> SEC[Content security scan]
    SEC --> CH[Structure-aware chunking]
    CH --> EMB
    EMB --> PG
    CH --> PG
    IW --> OBJ

    A --> QS[Query Service]
    QS --> PLAN[Query planning / normalization]
    PLAN --> HYB[Permission-aware hybrid retrieval]
    HYB --> PG
    HYB --> RR
    RR --> PACK[Context selection]
    PACK --> LLM
    LLM --> CV[Citation validation]
    CV --> W

    A --> AUD[(Audit Events)]
    A --> OBS
    IW --> OBS
```

### 4.1 Logical deployment units

- `web`: Next.js frontend.
- `api`: FastAPI application.
- `worker-ingestion`: Celery workers for parsing, chunking, embedding and indexing.
- `worker-sync`: connector synchronization workers; may share worker code initially.
- `dispatcher`: transactional-outbox dispatcher; can run as a lightweight worker/beat process.
- `scheduler`: periodic source sync, cleanup, orphan detection and evaluation schedules.
- PostgreSQL + pgvector.
- Redis.
- Object storage.
- OIDC identity provider.
- Optional local model service for embeddings/reranking/generation.
- Observability/evaluation backend.

---

## 5. Technology choices

### 5.1 Backend

- Python 3.12+.
- FastAPI.
- Pydantic v2.
- SQLAlchemy 2 async ORM/core.
- Alembic migrations.
- `uv` for Python dependency/project management.
- Celery for background work.
- Redis as broker/cache/rate-limit coordination.
- HTTPX for outbound HTTP.
- Tenacity or an equivalent bounded retry helper for provider calls.
- structlog or standard JSON logging.
- OpenTelemetry instrumentation.

### 5.2 Storage

- PostgreSQL 17/18 where supported by hosting environment.
- pgvector.
- PostgreSQL FTS (`tsvector`, `tsquery`, `ts_rank_cd`) for lexical retrieval.
- `pg_trgm` for identifier/fuzzy fallback and languages where stemming is not available.
- S3-compatible object storage.
- Redis for ephemeral coordination only; PostgreSQL remains the durable source of workflow state.

### 5.3 Parsing and document processing

Primary parser: **Docling**.

Core first-release formats:

- PDF (native and scanned);
- DOCX;
- PPTX;
- XLSX;
- CSV;
- HTML;
- Markdown;
- plain text;
- PNG/JPEG/TIFF for OCR-based text extraction.

Store a canonical parsed JSON artifact so chunking/indexing can be reproduced without reparsing the original binary.

### 5.4 Retrieval and model defaults

Use interfaces, but provide a working reference configuration:

- Embedding dimension standardized to **1024** for the first index schema.
- Local embedding profile: a multilingual 1024-dimension model such as Qwen3-Embedding-0.6B or an evaluated equivalent.
- Cloud embedding profile: an embedding provider configured to the project dimension where supported.
- Local reranker profile: Qwen3-Reranker-0.6B or an evaluated equivalent.
- Generation: provider-neutral LLM interface with at least one cloud provider and one local OpenAI-compatible endpoint/Ollama/vLLM-style adapter.

Do not hard-code the actual model as a business rule. Model IDs and provider configuration live in environment/configuration, while index generations record the exact model used.

### 5.5 Frontend

- Next.js + TypeScript, React Server Components where appropriate and client components only for interactive surfaces.
- React.
- Tailwind CSS.
- shadcn/ui + Radix primitives as an accessibility-focused component foundation, restyled into the KnowledgeOS visual system rather than using stock shadcn appearance.
- **Motion for React (`motion/react`)** for purposeful layout transitions, shared-element transitions, enter/exit states, gestures, rank reordering and onboarding/marketing motion.
- TanStack Query for server state and mutations.
- TanStack Table + virtualization for document, audit and evaluation data grids.
- Zod for frontend validation and API boundary parsing.
- Server-Sent Events (SSE) for answer streaming and query-stage updates.
- PDF.js/react-pdf or equivalent source viewer capable of opening a cited page, highlighting cited spans and preserving viewer position.
- Command-palette primitive (`cmdk` or equivalent) for global search/navigation.
- Recharts or a lightweight accessible charting layer for operational metrics; charts must remain secondary to inspectable tables.
- Lucide or equivalent restrained line-icon set. Avoid decorative AI/sparkle iconography as the primary visual language.

The frontend must follow the detailed design and motion specification in Section 27.

### 5.6 Identity

Use standard OIDC rather than inventing authentication cryptography.

- Local development: Keycloak is a suitable reproducible OIDC provider.
- Hosted environment: any standards-compliant managed OIDC provider can replace it.
- API validates JWT signature, issuer, audience, expiration and subject using provider JWKS.
- Application authorization remains in KnowledgeOS, not in the identity provider.

### 5.7 Observability and evaluation

- OpenTelemetry for request/job spans.
- Langfuse or equivalent for LLM/RAG traces, datasets and production evaluation.
- Ragas for offline RAG metrics where appropriate.
- Prometheus-compatible metrics + Grafana-compatible dashboards for infrastructure/service metrics.

### 5.8 Quality tooling

Backend:

- Ruff formatting/linting.
- mypy or Pyright strict-enough type checking.
- pytest.
- pytest-asyncio.
- Hypothesis for selected authorization/filter invariants.
- Testcontainers for integration tests.

Frontend:

- ESLint.
- TypeScript strict mode.
- Vitest/Jest.
- Playwright E2E.

Security/supply chain:

- Gitleaks.
- Semgrep.
- pip-audit.
- npm/pnpm audit.
- Trivy container scanning.
- SBOM generation for release images.

---

## 6. Repository layout

```text
knowledgeos/
├─ apps/
│  ├─ api/
│  │  ├─ app/
│  │  │  ├─ api/
│  │  │  │  ├─ dependencies/
│  │  │  │  └─ v1/
│  │  │  ├─ auth/
│  │  │  ├─ core/
│  │  │  ├─ db/
│  │  │  ├─ domain/
│  │  │  ├─ ingestion/
│  │  │  ├─ rag/
│  │  │  │  ├─ planning/
│  │  │  │  ├─ retrieval/
│  │  │  │  ├─ fusion/
│  │  │  │  ├─ reranking/
│  │  │  │  ├─ context/
│  │  │  │  ├─ generation/
│  │  │  │  ├─ citations/
│  │  │  │  └─ evaluation/
│  │  │  ├─ providers/
│  │  │  │  ├─ llm/
│  │  │  │  ├─ embeddings/
│  │  │  │  ├─ rerankers/
│  │  │  │  ├─ storage/
│  │  │  │  ├─ search/
│  │  │  │  └─ identity/
│  │  │  ├─ security/
│  │  │  ├─ services/
│  │  │  ├─ observability/
│  │  │  └─ workers/
│  │  ├─ migrations/
│  │  └─ pyproject.toml
│  └─ web/
│     ├─ app/
│     ├─ components/
│     ├─ features/
│     ├─ lib/
│     ├─ hooks/
│     ├─ types/
│     └─ tests/
├─ packages/
│  └─ contracts/          # generated/shared API schemas where useful
├─ evals/
│  ├─ datasets/
│  ├─ rubrics/
│  ├─ experiments/
│  └─ scripts/
├─ tests/
│  ├─ integration/
│  ├─ security/
│  ├─ load/
│  └─ e2e/
├─ infra/
│  ├─ docker/
│  ├─ compose/
│  ├─ terraform/
│  └─ monitoring/
├─ configs/
│  ├─ prompts/
│  ├─ rag_profiles/
│  └─ policies/
├─ docs/
│  ├─ adr/
│  ├─ architecture/
│  ├─ threat-model/
│  ├─ api/
│  ├─ runbooks/
│  └─ evaluation/
├─ scripts/
├─ .github/workflows/
├─ docker-compose.yml
├─ Makefile
├─ README.md
└─ PLAN.md
```

Do not introduce separate repositories until there is an operational reason.

---

## 7. Core domain and database model

### 7.1 Identifier and timestamp rules

- Use UUID primary keys.
- Store timestamps as timezone-aware UTC.
- All tenant-scoped durable tables contain `organization_id` explicitly, even when it can be reached through joins. This supports RLS, auditability and safer queries.
- Never use user-controlled slugs as authorization identifiers.
- Soft-deletion may be used for business history, but deleted content must be excluded from retrieval immediately and later physically purged according to retention policy.

### 7.2 Identity/organization tables

#### `users`

- `id`
- `external_subject` (OIDC `sub`, unique per issuer)
- `issuer`
- `email`
- `display_name`
- `status`
- `created_at`
- `last_seen_at`

#### `organizations`

- `id`
- `name`
- `slug`
- `status`
- `created_at`
- `settings_json`

#### `memberships`

- `organization_id`
- `user_id`
- `role_id`
- `status`
- `joined_at`

Unique `(organization_id, user_id)`.

#### `roles`

Create default roles but use permission strings internally.

Default roles:

- owner;
- admin;
- knowledge_manager;
- member;
- viewer.

#### `role_permissions`

Examples:

- `org.manage`
- `members.manage`
- `groups.manage`
- `kb.create`
- `kb.manage`
- `document.upload`
- `document.publish`
- `document.delete`
- `query.execute`
- `retrieval.debug`
- `evaluation.manage`
- `audit.read`
- `api_keys.manage`
- `model_policy.manage`

#### `groups`

- `id`
- `organization_id`
- `name`
- `description`

#### `group_memberships`

- `group_id`
- `user_id`

### 7.3 Knowledge and permissions

#### `knowledge_bases`

- `id`
- `organization_id`
- `name`
- `slug`
- `description`
- `visibility` (`organization`, `restricted`)
- `active_index_generation_id`
- `active_rag_profile_version_id`
- `model_policy_id`
- `retention_policy_id`
- `created_by`
- `created_at`
- `archived_at`

#### `knowledge_base_acl`

Allow-only ACL for v1 to avoid ambiguous allow/deny resolution.

- `knowledge_base_id`
- `principal_type` (`user`, `group`, `role`)
- `principal_id`
- `permission` (`query`, `manage`)

#### `document_acl`

- `document_id`
- `principal_type`
- `principal_id`
- `permission`

Document ACL can inherit KB ACL or be more restrictive. Do not permit a document to widen a restricted KB beyond organizational policy.

### 7.4 Source and document tables

#### `data_sources`

- `id`
- `organization_id`
- `knowledge_base_id`
- `type` (`upload`, `web`, `google_drive`, `sharepoint`, etc.)
- `name`
- `status`
- `trust_level`
- `permission_sync_mode`
- `encrypted_config_ref`
- `sync_cursor`
- `last_sync_at`
- `last_sync_status`
- `created_by`

#### `source_objects`

Maps external records to logical documents.

- `id`
- `source_id`
- `external_id`
- `external_revision`
- `document_id`
- `source_url`
- `source_modified_at`
- `deleted_at`

#### `documents`

Logical document identity across versions.

- `id`
- `organization_id`
- `knowledge_base_id`
- `source_id`
- `canonical_key`
- `title`
- `document_type`
- `classification` (`public`, `internal`, `confidential`, `restricted`)
- `status`
- `active_version_id`
- `created_by`
- `created_at`
- `archived_at`

#### `document_versions`

Immutable source-version record.

- `id`
- `organization_id`
- `document_id`
- `version_number`
- `sha256`
- `object_key`
- `canonical_artifact_key`
- `mime_type`
- `size_bytes`
- `source_modified_at`
- `effective_from`
- `effective_to`
- `parser_name`
- `parser_version`
- `integrity_status`
- `approval_status`
- `ingestion_status`
- `created_at`

### 7.5 Ingestion workflow tables

#### `ingestion_jobs`

- `id`
- `organization_id`
- `document_version_id`
- `index_generation_id`
- `state`
- `stage`
- `progress_percent`
- `attempt_count`
- `error_code`
- `error_detail_safe`
- `started_at`
- `completed_at`
- `heartbeat_at`

#### `outbox_events`

- `id`
- `organization_id`
- `event_type`
- `aggregate_type`
- `aggregate_id`
- `payload_json`
- `created_at`
- `published_at`
- `attempt_count`

The row is created in the same DB transaction as the business state change.

### 7.6 Index and chunk tables

#### `index_generations`

Each KB has one active generation and may temporarily have candidate/previous generations.

- `id`
- `organization_id`
- `knowledge_base_id`
- `generation_number`
- `status` (`building`, `candidate`, `active`, `retired`, `failed`)
- `embedding_provider`
- `embedding_model`
- `embedding_dimension` (1024 for first schema)
- `chunker_name`
- `chunker_config_json`
- `parser_pipeline_version`
- `retrieval_profile_version_id`
- `created_at`
- `activated_at`
- `retired_at`

#### `chunks`

A chunk belongs to a particular document version and index generation, allowing side-by-side reindexing.

- `id`
- `organization_id`
- `knowledge_base_id`
- `document_id`
- `document_version_id`
- `index_generation_id`
- `ordinal`
- `parent_chunk_id` nullable
- `block_type`
- `section_path`
- `content`
- `content_hash`
- `token_count`
- `page_start`
- `page_end`
- `bbox_json` optional
- `metadata_json`
- `visibility`
- `access_principals` (array of normalized principal tokens)
- `embedding` (`vector(1024)` in first schema)
- `search_vector` (`tsvector`)
- `created_at`

`access_principals` examples:

```text
user:UUID
group:UUID
role:member
org:UUID
```

Every retrieved chunk must carry the authorization metadata of its parent document.

### 7.7 RAG configuration tables

#### `rag_profiles`

Treat versions as immutable.

- `id`
- `organization_id` nullable for system presets
- `name`
- `version`
- `config_json`
- `prompt_version`
- `status` (`draft`, `candidate`, `active`, `retired`)
- `created_by`
- `created_at`

A profile contains:

- dense retrieval K;
- lexical retrieval K;
- fusion method/weights;
- rerank candidate count;
- final context K;
- max context tokens;
- diversity limits;
- rewrite/decomposition switches;
- calibrated abstention thresholds;
- generation model policy;
- prompt version.

#### `model_policies`

- allowed generation providers;
- allowed embedding providers;
- allowed reranking providers;
- local-only flag;
- maximum classification permitted for external providers;
- primary generation model;
- allowed generation fallbacks;
- embedding model tied to index-generation creation;
- reranker model/version.

### 7.8 Conversation/query tables

#### `conversations`

- `id`
- `organization_id`
- `knowledge_base_id`
- `user_id`
- `title`
- `created_at`
- `updated_at`
- `retention_expires_at`

#### `messages`

- `id`
- `conversation_id`
- `role`
- `content` or encrypted/content-retention representation according to policy
- `created_at`

Conversation history is **not** inserted into the knowledge corpus.

#### `query_runs`

- `id`
- `organization_id`
- `knowledge_base_id`
- `user_id`
- `conversation_id`
- `trace_id`
- `query_text` only when retention policy permits; otherwise hash/redacted form
- `query_language`
- `query_type`
- `rag_profile_version_id`
- `index_generation_id`
- `generation_model`
- `status`
- `retrieval_latency_ms`
- `rerank_latency_ms`
- `generation_latency_ms`
- `total_latency_ms`
- `created_at`

#### `retrieval_hits`

- `query_run_id`
- `chunk_id`
- `dense_rank`
- `dense_score`
- `lexical_rank`
- `lexical_score`
- `fusion_score`
- `rerank_score`
- `selected_for_context`

#### `answers`

- `id`
- `query_run_id`
- `answer_markdown` if retention permits
- `abstained`
- `abstain_reason`
- `input_tokens`
- `output_tokens`
- `estimated_cost`
- `created_at`

#### `citations`

- `answer_id`
- `source_alias`
- `chunk_id`
- `document_version_id`
- `page_start`
- `page_end`
- `validated_identifier`

### 7.9 Feedback/evaluation/audit

#### `feedback`

- `query_run_id`
- `user_id`
- `rating` (`up`, `down`)
- `reason_code`
- `comment` optional
- `created_at`

#### `eval_datasets`, `eval_cases`, `eval_runs`, `eval_results`

Persist dataset version, git SHA, active profile, index generation, model versions and metric versions.

#### `audit_events`

Append-only logical audit stream:

- `id`
- `organization_id`
- `actor_type`
- `actor_id`
- `action`
- `resource_type`
- `resource_id`
- `request_id`
- `metadata_json` excluding secrets/content by default
- `created_at`

### 7.10 API keys

Store only hashed secret material.

- key ID / public prefix;
- secret hash;
- organization;
- scopes;
- created by;
- expiration;
- last used;
- revoked at.

---

## 8. Database indexes and Row-Level Security

### 8.1 Required indexes

- B-tree on major `(organization_id, ...)` access paths.
- B-tree on `(knowledge_base_id, index_generation_id)`.
- B-tree on `(document_id, version_number)`.
- GIN on `chunks.search_vector`.
- GIN on `chunks.access_principals`.
- HNSW on `chunks.embedding vector_cosine_ops`.
- B-tree/GIN indexes on frequently filtered metadata fields rather than arbitrary JSON-only filtering.
- Unique constraints on membership, source-object identity and document version numbers.

### 8.2 Tenant RLS

All tenant-scoped tables use PostgreSQL RLS as a second line of defense.

At the start of each DB transaction, middleware/repository code sets transaction-local context such as:

```text
app.organization_id
app.user_id
```

RLS ensures a normal application connection cannot read rows from another organization.

Important implementation rule: do not keep a DB transaction open while the LLM streams a response. Retrieval finishes, required source data is materialized into application memory, the DB transaction closes, and only then does generation continue.

### 8.3 Within-tenant ACL

RLS guarantees tenant isolation. Document/KB ACL additionally limits content inside a tenant.

The retrieval query must include:

- correct organization;
- correct KB;
- active index generation;
- active document version;
- document not archived/deleted;
- allowed visibility/access-principal predicate.

The same authorization metadata is copied onto every chunk. Never retrieve unauthorized chunks and filter them after ranking.

### 8.4 pgvector filtered retrieval

Because approximate vector indexes apply filtering in ways that can reduce returned candidates, enable and test appropriate HNSW iterative scanning and increase candidate search only based on benchmark results. For workloads where shared approximate indexes materially degrade tenant recall, migrate the affected retrieval backend through the search abstraction instead of rewriting the application.

---

## 9. Secure upload flow

### 9.1 Browser upload sequence

1. Client calls `POST /v1/kbs/{kb_id}/uploads` with filename, content type and expected size.
2. API authorizes `document.upload` and validates declared limits.
3. API creates an upload record and returns a short-lived presigned upload URL to a **quarantine** bucket/prefix.
4. Browser uploads directly to object storage.
5. Client calls `POST /v1/uploads/{upload_id}/complete`.
6. API performs object HEAD verification and creates the logical document/document-version plus outbox event in one transaction.
7. Dispatcher publishes an ingestion job.
8. Worker validates and scans the quarantined object before promoting it to trusted storage.

### 9.2 File-safety checks

Perform before parsing:

- file-size limit;
- MIME sniffing from actual bytes, not extension alone;
- extension/MIME consistency checks;
- anti-malware scanning;
- archive/decompression ratio limits;
- encrypted/password-protected file policy;
- page/dimension limits for PDFs/images;
- rejection of executable/script types;
- parser time/memory limits;
- no Office macro execution;
- SHA-256 fingerprint;
- duplicate detection **within the tenant/KB only** to avoid cross-tenant side channels.

### 9.3 Provenance

Store:

- uploader/source;
- source connector;
- source external ID;
- source revision;
- upload timestamp;
- SHA-256;
- parser version;
- approval state;
- original object key;
- canonical artifact key.

High-risk or untrusted sources can require knowledge-manager approval before becoming searchable.

---

## 10. Canonical document processing

### 10.1 Canonical representation

Normalize all formats into a common internal artifact containing blocks:

```text
CanonicalDocument
- title
- language(s)
- metadata
- blocks[]
    - block_id
    - type: heading | paragraph | list | table | code | caption | image_text
    - text / structured table representation
    - page
    - bbox
    - heading_path
    - source_order
```

Persist this artifact as JSON in object storage.

### 10.2 Format-specific behavior

**PDF**
- preserve page number;
- preserve headings where detected;
- preserve reading order;
- OCR scanned pages;
- retain bounding boxes when available so citations can later highlight source areas.

**DOCX**
- preserve heading hierarchy, paragraphs, lists and tables.

**PPTX**
- treat slide title + slide text + notes as a logical unit;
- preserve slide number.

**XLSX/CSV**
- preserve sheet name;
- detect headers;
- serialize manageable row groups with headers repeated;
- preserve row ranges as citation metadata;
- do not pretend text RAG is a complete substitute for analytical SQL.

**HTML/Web**
- retain canonical URL, title and headings;
- remove navigation/cookie boilerplate;
- preserve useful tables/code.

**Images/scans**
- OCR text;
- record OCR confidence where available;
- low-confidence extraction should be visible in document diagnostics.

### 10.3 Normalization

- Unicode normalization.
- normalize whitespace without destroying table/code structure.
- remove known invisible-control abuse while preserving a forensic copy in the canonical artifact if security policy needs it.
- detect language.
- detect repeated headers/footers in PDFs.
- retain source text; do not aggressively “clean” away legally meaningful text.

---

## 11. RAG content-security pipeline

The scanner is defense-in-depth, not the sole security boundary.

Inspect canonical content for:

- obvious indirect prompt-injection phrases;
- fake system/user messages;
- hidden/zero-width character abuse;
- suspicious encoded instruction blocks;
- malicious hyperlinks;
- abnormally large repeated text intended to dominate retrieval;
- unexpected content-type mismatch.

Outcomes:

- `clean`: normal processing;
- `flagged`: searchable only if policy permits and marked in provenance;
- `quarantined`: admin review required;
- `rejected`: unsupported or malicious binary/content pattern.

Never assume a scanner makes retrieved text trusted. Generation prompts must still mark all retrieved content as untrusted evidence.

---

## 12. Chunking design

### 12.1 Default strategy

Use **structure-aware parent/child chunking**.

Initial configuration for evaluation, not an immutable constant:

- target child size: ~600 tokens;
- overlap: ~80 tokens only when a structural boundary does not provide continuity;
- minimum useful chunk: ~80 tokens;
- parent sections: bounded sections of ~1,500–2,500 tokens where possible;
- table chunking: table-header aware;
- max context expansion controlled separately from index chunk size.

### 12.2 Rules

1. Never split a heading away from the content it describes.
2. Add document title + heading path as retrieval context.
3. Avoid mixing unrelated sections merely to reach a token target.
4. Preserve page/slide/row metadata.
5. For long tables, repeat headers in each table chunk.
6. For code/runbooks, preserve fenced/code blocks and nearby explanation.
7. Compute content hash for each chunk.
8. Store the exact chunker version/config in the index generation.

### 12.3 Embedding text vs display text

Create `embedding_text` conceptually as:

```text
Document title
Section path
Optional metadata labels
Chunk body
```

The generation context uses the source chunk body and source metadata, not an artificial rewritten passage unless explicitly evaluated.

### 12.4 Alternative chunkers behind experiments

- recursive fixed-token;
- pure structure-aware;
- semantic boundary detection;
- sentence-window retrieval;
- parent-child retrieval.

Only promote a different strategy when offline evaluation shows a measurable improvement without unacceptable latency/cost regression.

---

## 13. Embedding and index-generation strategy

### 13.1 Embedding rules

- Batch embeddings.
- Normalize if required by model/retrieval metric.
- Store provider/model/version/dimension.
- Cache embeddings by `model_id + normalized_embedding_text_hash` **inside the same security boundary**.
- Never silently use a different model when the selected embedding provider is unavailable.

### 13.2 Index generations

Any change to one of these should normally create a candidate generation:

- embedding model/dimension;
- major parser behavior;
- chunking strategy;
- metadata schema affecting retrieval;
- lexical-index strategy.

Lifecycle:

```text
CREATE CANDIDATE
      ↓
REPROCESS / RE-EMBED
      ↓
CANDIDATE READY
      ↓
OFFLINE EVALUATION
      ↓
SECURITY REGRESSION
      ↓
ADMIN / DEPLOYMENT APPROVAL
      ↓
ATOMIC ACTIVE-GENERATION SWITCH
      ↓
MONITOR
      ↓
RETAIN PREVIOUS FOR ROLLBACK
      ↓
GARBAGE-COLLECT AFTER RETENTION WINDOW
```

This enables zero-downtime retrieval changes and rollback.

---

## 14. Ingestion job state machine

```text
RECEIVED
  ↓
VALIDATING
  ↓
MALWARE_SCAN
  ↓
PARSING
  ↓
NORMALIZING
  ↓
SECURITY_SCAN
  ↓
CHUNKING
  ↓
EMBEDDING
  ↓
INDEXING
  ↓
VERIFYING
  ↓
READY
```

Alternative terminal/intermediate states:

- `PENDING_APPROVAL`
- `QUARANTINED`
- `FAILED_RETRYABLE`
- `FAILED_PERMANENT`
- `CANCELLED`

### 14.1 Reliability rules

- Each stage is idempotent.
- Worker retries use exponential backoff + jitter.
- Retries have bounded maximum attempts.
- Stage outputs are durable enough to resume after worker death.
- Heartbeats detect stuck jobs.
- A reconciliation task periodically finds orphaned/incomplete jobs.
- An advisory lock/idempotency key prevents two workers from indexing the same document version/generation simultaneously.
- User-visible progress is stored in PostgreSQL, not inferred from Celery internal state.

---

## 15. Connector architecture

Define a connector protocol:

```text
Connector
- validate_configuration()
- discover_changes(cursor)
- fetch_object(external_id)
- fetch_metadata(external_id)
- fetch_permissions(external_id)
- get_revision(external_id)
- acknowledge_cursor()
```

### 15.1 First connector sequence

1. Manual upload.
2. Controlled website/sitemap ingestion.
3. Google Drive.
4. SharePoint/OneDrive or Confluence, depending portfolio goals.

### 15.2 Sync behavior

A connector sync must detect:

- new objects;
- changed revisions;
- deleted objects;
- permission changes;
- moved/renamed items.

Permission-only changes are security-critical and must update chunk ACLs even if document text did not change.

### 15.3 Web crawler security

The web connector must prevent SSRF:

- user-configured allowed domains;
- reject loopback/private/link-local/metadata IP destinations;
- validate redirects;
- protect against DNS rebinding;
- enforce response-size/time limits;
- restrict protocols to HTTP/HTTPS;
- obey configured robots/sitemap policy;
- max depth/page count;
- sanitize canonical URLs.

---

## 16. Query execution pipeline

### 16.1 Request lifecycle

```text
Authenticate
  ↓
Resolve organization + membership + KB access
  ↓
Load active index generation + RAG profile + model policy
  ↓
Normalize/query-safety checks
  ↓
Classify query type
  ↓
Optional history rewrite / query decomposition
  ↓
Build typed metadata filters
  ↓
Build authorization principal set
  ↓
Dense retrieval + lexical retrieval in parallel
  ↓
Rank fusion
  ↓
Deduplicate/diversify
  ↓
Cross-encoder reranking
  ↓
Evidence sufficiency decision
  ↓
Context packing / optional neighbor expansion
  ↓
Generation using untrusted-evidence delimiters
  ↓
Citation identifier validation
  ↓
Stream/return answer
  ↓
Feedback/evaluation/trace logging
```

### 16.2 Query normalization

- trim and normalize whitespace;
- Unicode normalization;
- max query length;
- language detection;
- retain original query for trace if policy permits;
- detect abuse/reconnaissance patterns for monitoring;
- do not “sanitize” away meaningful business terms.

### 16.3 Query types

Start with deterministic/simple routing, not an expensive agent.

Supported types:

- `fact_lookup`;
- `document_navigation`;
- `comparison`;
- `document_summary`;
- `broad_topic`;
- `unsupported_exhaustive_or_aggregate`.

Behavior:

- **Fact:** normal hybrid RAG.
- **Navigation:** strongly boost exact title/identifier metadata.
- **Comparison:** decompose into bounded subqueries, retrieve evidence for each side, then compare.
- **Document summary:** require a selected or resolved document scope; use hierarchical summarization if the document is too large.
- **Exhaustive/list/aggregate:** use structured metadata/search APIs or explicitly state that RAG retrieval is not guaranteed exhaustive.

### 16.4 Conversation-aware query rewriting

Only rewrite when the current message contains references such as “that policy”, “what about last year?”, etc.

Rules:

- retain original and rewritten query in trace;
- do not broaden security scope;
- do not allow the rewrite model to invent filters;
- if rewrite fails, search original query.

---

## 17. Typed metadata filtering

Never let an LLM generate raw SQL.

Define a Pydantic `QueryFilters` schema containing explicitly allowed fields, for example:

- document IDs;
- source IDs;
- document type;
- tags;
- department;
- source modified date range;
- effective date range;
- language.

LLM-derived filters are treated as hints and validated.

If an automatically inferred non-security filter causes zero results, the system may retry once with that inferred filter relaxed. **Authorization filters are never relaxed.**

---

## 18. Hybrid retrieval

### 18.1 Dense retrieval

Reference starting value:

- retrieve top ~50 authorized candidates using cosine similarity.

The SQL predicate includes organization, KB, active generation, active version and ACL before result selection.

### 18.2 Lexical retrieval

Use PostgreSQL full-text search:

- weighted title/section/body `tsvector`;
- `websearch_to_tsquery` for user-style input;
- rank using `ts_rank_cd` or evaluated alternative;
- exact identifier/title boosts;
- `pg_trgm` fallback where useful.

Reference candidate count: ~50.

For multilingual corpora, use appropriate FTS configuration where available and `simple`/trigram fallback where linguistic stemming is unavailable. Dense multilingual retrieval remains important.

### 18.3 Fusion

Use Reciprocal Rank Fusion initially because lexical and vector scores are not directly comparable.

Reference experimental configuration:

```text
RRF constant k0 = 60
dense weight   = 0.55
lexical weight = 0.45
```

These values are **baseline experiment settings**, not production truth. Tune with evaluation.

### 18.4 Candidate diversity

Before reranking:

- merge duplicate chunk IDs;
- cap near-identical duplicate content;
- apply a maximum candidate contribution per document if a single document floods results;
- preserve enough same-document continuity for factual answers.

Avoid MMR or diversity heuristics unless evaluation demonstrates value.

---

## 19. Reranking

Reference flow:

```text
~100 raw candidates
      ↓
RRF / dedupe
      ↓
Top 30 fused candidates
      ↓
Cross-encoder reranker
      ↓
Top 6–8 evidence chunks
```

Requirements:

- reranker interface supports local or hosted model;
- record model ID and version;
- batch candidate pairs;
- timeout is bounded;
- if reranker is unavailable and profile permits degradation, use fused ranking and mark trace as degraded;
- model-specific relevance thresholds must be calibrated using the no-answer evaluation set.

Do not compare raw reranker scores across different models.

---

## 20. Context construction

### 20.1 Evidence packing

Use a token budget rather than “top K only”.

Initial evidence budget: roughly 4,000–5,000 tokens, tuned per generation model and evaluation.

Selection considers:

- rerank score;
- document diversity;
- source freshness/effective date only where business semantics require it;
- neighbor expansion for fragments that need continuity;
- maximum chunks per document;
- avoidance of redundant text.

### 20.2 Source aliases

Assign immutable per-answer aliases:

```text
[S1]
[S2]
...
```

For each alias store:

- chunk ID;
- document title;
- document version;
- page/slide/row range;
- section path;
- source URL/object location;
- content hash.

### 20.3 Trust boundary

The model prompt must clearly delimit sources as **untrusted evidence, not instructions**.

Retrieved content may never introduce new tool permissions, system instructions or access rules.

---

## 21. Answer generation

### 21.1 Generation contract

The system prompt requires the model to:

- answer business facts only from supplied evidence;
- cite evidence using only provided aliases;
- state when evidence is insufficient;
- mention material conflicts between sources rather than silently choosing one;
- prefer explicitly effective/current source versions when query semantics imply “current”;
- not follow instructions appearing inside retrieved source text;
- not reveal hidden/system prompts;
- not fabricate source names, page numbers or citations.

### 21.2 No-answer behavior

Do not force an answer.

If evidence is insufficient:

- return a concise abstention;
- optionally show the closest authorized sources;
- allow the user to broaden the query or select a document;
- record the event for evaluation.

### 21.3 “Confidence” UX

Do not expose an invented probability from the LLM.

If the UI needs a trust signal, use a calibrated **evidence status** such as:

- strong evidence;
- partial evidence;
- insufficient evidence.

Derive it from evaluated retrieval/citation rules, not the model saying “95% confident.”

### 21.4 Contradictions

When two authoritative sources conflict:

- show both;
- include document version/effective date;
- explain the conflict neutrally;
- never hide one merely because its rerank score is slightly lower.

---

## 22. Citation validation

At minimum, production must validate mechanically that:

- every cited `[Sx]` exists in the selected context;
- the alias points to an authorized chunk;
- page/section metadata comes from stored source metadata, never model-generated metadata;
- no unknown citation aliases survive the response.

Recommended additional checks:

- require citations after factual paragraphs/sentences according to prompt style;
- optionally run a lightweight claim-support verifier on sampled or high-risk answers;
- evaluate semantic citation support offline across the golden set.

If citation identifiers are invalid:

1. attempt one bounded regeneration/correction;
2. if still invalid, fail safely rather than presenting fabricated citations.

---

## 23. Streaming protocol

Use SSE.

Suggested events:

```text
meta          # query id, trace id, model/profile information safe for client
sources       # selected source aliases and metadata
answer_delta  # text tokens/chunks
citation      # optional validated citation updates
done          # usage, abstention state, timing summary
error         # safe error code/message
```

Do not expose raw internal prompts, unauthorized candidates or provider exception dumps.

---

## 24. Conversation memory

- Store conversation messages separately from enterprise knowledge.
- Use only a bounded history window or conversation summary for query rewrite.
- Never allow a prior assistant answer to become authoritative evidence unless it is re-grounded against the corpus.
- Tenant/KB access is rechecked on every turn.
- If permissions change mid-conversation, future turns must use current permissions.
- Conversation retention is configurable.

---

## 25. Model/provider abstraction

Define interfaces such as:

```python
class EmbeddingProvider:
    async def embed_documents(...): ...
    async def embed_query(...): ...

class RerankerProvider:
    async def rerank(...): ...

class LLMProvider:
    async def generate(...): ...
    async def stream(...): ...

class SearchBackend:
    async def hybrid_search(...): ...

class ObjectStore:
    ...
```

### 25.1 Model policy behavior

A KB can be configured as:

- cloud allowed;
- local preferred with cloud fallback;
- **local only**.

Policy applies independently to:

- document embedding;
- query embedding;
- reranking;
- generation.

A restricted/local-only KB must never send retrieved text to a cloud generation service, and must not send document/query text to a cloud embedding/reranking provider unless explicitly allowed.

### 25.2 Provider failure policy

- Generation model: may fall back only to an allowed compatible model.
- Reranker: may be bypassed if profile explicitly permits degraded mode.
- Vector search: may fall back to lexical-only if authorized and traced.
- Lexical search: may fall back to vector-only if authorized and traced.
- Embedding model during query: **do not substitute another embedding model against an existing index**.
- Authorization failure: never degrade; fail closed.

---

## 26. API design

All routes versioned under `/v1`.

### 26.1 General rules

- JSON error envelope with stable machine-readable error codes.
- Cursor pagination, not unbounded offset pagination for large collections.
- Idempotency key support for important create/finalize operations.
- OpenAPI documentation.
- Request IDs propagated to logs/traces.
- Scope-based API keys.
- No secrets in response bodies.

### 26.2 Major endpoints

#### Identity/org

```text
GET    /v1/me
GET    /v1/organizations
POST   /v1/organizations
GET    /v1/organizations/{org_id}/members
POST   /v1/organizations/{org_id}/invitations
PATCH  /v1/organizations/{org_id}/members/{user_id}
DELETE /v1/organizations/{org_id}/members/{user_id}
GET    /v1/organizations/{org_id}/groups
POST   /v1/organizations/{org_id}/groups
```

#### Knowledge bases

```text
GET    /v1/knowledge-bases
POST   /v1/knowledge-bases
GET    /v1/knowledge-bases/{kb_id}
PATCH  /v1/knowledge-bases/{kb_id}
DELETE /v1/knowledge-bases/{kb_id}
GET    /v1/knowledge-bases/{kb_id}/permissions
PUT    /v1/knowledge-bases/{kb_id}/permissions
```

#### Upload/documents

```text
POST   /v1/knowledge-bases/{kb_id}/uploads
POST   /v1/uploads/{upload_id}/complete
GET    /v1/knowledge-bases/{kb_id}/documents
GET    /v1/documents/{document_id}
GET    /v1/documents/{document_id}/versions
POST   /v1/documents/{document_id}/versions
POST   /v1/documents/{document_id}/reindex
DELETE /v1/documents/{document_id}
GET    /v1/ingestion-jobs/{job_id}
```

#### Retrieval/RAG

```text
POST   /v1/knowledge-bases/{kb_id}/search
POST   /v1/knowledge-bases/{kb_id}/query
POST   /v1/knowledge-bases/{kb_id}/query/stream
GET    /v1/query-runs/{query_run_id}
POST   /v1/query-runs/{query_run_id}/feedback
```

`/search` returns authorized retrieval results without generation and is valuable for debugging/integration.

#### Conversations

```text
GET    /v1/conversations
POST   /v1/conversations
GET    /v1/conversations/{id}
DELETE /v1/conversations/{id}
```

#### Sources/connectors

```text
GET    /v1/knowledge-bases/{kb_id}/sources
POST   /v1/knowledge-bases/{kb_id}/sources
POST   /v1/sources/{source_id}/sync
GET    /v1/sources/{source_id}/sync-runs
DELETE /v1/sources/{source_id}
```

#### RAG configuration/evaluation

```text
GET    /v1/knowledge-bases/{kb_id}/rag-profiles
POST   /v1/knowledge-bases/{kb_id}/rag-profiles
POST   /v1/rag-profiles/{profile_id}/evaluate
POST   /v1/rag-profiles/{profile_id}/activate
GET    /v1/evaluations
GET    /v1/evaluations/{run_id}
```

#### Admin/audit/usage

```text
GET    /v1/audit-events
GET    /v1/usage
GET    /v1/api-keys
POST   /v1/api-keys
DELETE /v1/api-keys/{key_id}
```

#### Operations

```text
GET /health/live
GET /health/ready
GET /metrics   # protected/private network only
```

---

## 27. Frontend experience, visual system and product specification

### 27.1 Product-design thesis

KnowledgeOS must look and behave like a **professional research and work-intelligence instrument**, not a generic AI chatbot/SaaS landing page.

The interface should combine four qualities:

1. **Source-first trust.** Evidence is always visually close to the claim it supports.
2. **Editorial clarity.** Long answers should read like a well-designed report, not a stack of chat bubbles.
3. **Enterprise density.** Tables, filters, statuses and metadata must be efficient for daily work.
4. **Calm motion.** Animation explains state and spatial relationships. It never competes with the information.

The desired feeling is closer to a research terminal, modern document editor and enterprise search product than to a consumer chatbot.

#### Explicit anti-patterns

Do not use the following as the default visual language:

- purple/blue aurora gradients;
- glowing animated AI orb;
- galaxy/star backgrounds;
- glassmorphism across the whole application;
- oversized 24–32 px rounded cards everywhere;
- every element placed inside a floating card;
- chat bubbles for assistant long-form answers;
- sparkle/wand icons next to every AI action;
- endless typewriter animations;
- bouncing loading dots with no indication of what the system is doing;
- decorative 3D scenes in the authenticated application;
- excessive parallax;
- large marketing copy consuming the working viewport;
- hidden citations available only through a tiny footnote;
- animation that delays an action after the underlying data is already available.

The product should remain visually recognizable even if all words such as “AI”, “RAG” and “assistant” are removed from the screen.

---

### 27.2 Design research translated into KnowledgeOS

The frontend should borrow **interaction principles**, not clone visual styling.

#### Glean — enterprise search as the front door

Adopt:

- global search/ask entry that can locate documents as well as answer questions;
- source scope controls;
- permission-aware results presented as a normal product capability rather than a security warning;
- citations that open real company content;
- connectors/apps represented as first-class knowledge sources;
- ability to move from “find” to “ask” without switching products.

Do not clone:

- Glean branding, exact layout or asset treatment.

#### NotebookLM — sources, conversation and work product as peers

Adopt:

- a persistent source-management surface;
- direct movement from citation → source → exact passage;
- source selection before a query when the user wants tight control;
- a workspace model where sources and generated outputs remain available beside the conversation;
- contextual suggested actions generated from the current source set.

KnowledgeOS should evolve this into an enterprise pattern: **Knowledge / Answer / Evidence**, rather than a simple chat layout.

#### Perplexity — explicit retrieval scope and citation ergonomics

Adopt:

- clear scope selection such as “Company”, “Web”, “Selected sources” and, when enabled, “Model only”;
- compact inline citations;
- source cards that can be inspected without losing the answer;
- collaborative project/workspace grouping;
- strong keyboard-first query workflow.

The scope control must show what data category will be searched **before** the query is submitted.

#### Hebbia Matrix — serious analysis is not always chat

Adopt:

- spreadsheet/table-like analysis for cross-document work;
- dense document rows and generated columns;
- expandable/collapsible analytical tables;
- project history/version awareness;
- source review before expensive/deep analysis.

KnowledgeOS should therefore include a future-ready **Compare / Matrix view** in addition to Chat. The first release can implement a constrained comparison table rather than a general autonomous Matrix agent.

#### RAGFlow — inspectability and knowledge artifacts

Adopt:

- citations with chunk metadata;
- visible knowledge-base state;
- transparent retrieval and ingestion configuration for advanced users;
- document parsing/chunk inspection;
- structured knowledge artifacts only when they genuinely help navigation.

#### Dify — configuration without forcing configuration on ordinary users

Adopt:

- retrieval settings such as metadata filters, thresholds and reranking in admin/developer screens;
- a visual distinction between application behavior and underlying knowledge configuration;
- sane defaults for employees, deep controls for administrators.

The final principle is **progressive disclosure**: ordinary users see simple search and evidence; administrators can drill all the way down to retrieval scores and chunk metadata.

---

### 27.3 Brand and visual direction — “Knowledge Instrument”

#### Personality

- precise;
- calm;
- literate;
- trustworthy;
- technical without looking like a developer dashboard;
- premium without looking luxurious or ornamental;
- dense when needed, quiet when reading.

#### Base color direction

Use a restrained neutral palette rather than an “AI gradient” palette.

Light mode reference tokens:

```css
--canvas:        #F4F3EE;   /* warm paper */
--surface-0:     #FAF9F5;
--surface-1:     #FFFFFF;
--surface-2:     #EEEDE7;
--ink:           #171918;
--ink-secondary: #515650;
--ink-tertiary:  #7A7F78;
--line:          #D9D9D1;
--line-strong:   #BCBEB6;
--accent:        #3448C5;   /* controlled ultramarine, not gradient */
--accent-soft:   #E8EAFB;
--success:       #2E7254;
--warning:       #A16318;
--danger:        #A54138;
--focus:         #5267E8;
```

Dark mode reference tokens:

```css
--canvas:        #101210;
--surface-0:     #141714;
--surface-1:     #191C19;
--surface-2:     #202420;
--ink:           #F1F0EA;
--ink-secondary: #B9BDB5;
--ink-tertiary:  #858B82;
--line:          #2E332E;
--line-strong:   #454C45;
--accent:        #8997FF;
--accent-soft:   #242948;
```

These are starting tokens, not immutable branding. Before final release, validate contrast and adjust to WCAG requirements.

#### Color rules

- Accent color is used for focus, active selection, links, primary action and evidence linkage.
- Do not use accent as a full-page background.
- Success/warning/danger are semantic only.
- Source type may have a tiny colored marker, but the same type must always use the same color.
- Data visualizations must use accessible non-color differentiators where required.

#### Shape language

- Default control radius: 7–9 px.
- Panels: 10–12 px when a panel truly needs containment.
- Pills only for tags, filters, statuses and compact segmented controls.
- Do not make ordinary buttons pill shaped by default.
- Border hierarchy is preferred over large shadows.
- Shadows are subtle and reserved for transient elevation: menus, popovers, command palette and dragged items.

#### Typography

Recommended hierarchy:

- UI/navigation: **Instrument Sans** or another evaluated humanist/grotesk sans.
- Long answer/report reading: **Source Serif 4** optional reading face, especially for report mode.
- Code, IDs, scores, hashes and trace values: **IBM Plex Mono**.

Fallbacks must keep the application usable without custom-font loading.

Rules:

- Base UI size: 14 px on desktop; never shrink dense tables below accessible legibility.
- Main reading content: 16–18 px with generous line height and a maximum readable line length around 72–80 characters.
- Use tabular numerals for metrics.
- Use weight and spacing before using many font sizes.
- Generated answer headings follow document typography, not chat-message typography.

#### Iconography

- restrained line icons;
- icons never replace labels for ambiguous enterprise actions;
- source/provider icons can use official marks where licensing permits;
- avoid “magic wand”, robot head and sparkle motifs as generic AI decoration.

---

### 27.4 Information architecture

Authenticated navigation should be task-oriented.

```text
KnowledgeOS
├─ Home
├─ Ask
├─ Search
├─ Knowledge
│  ├─ Libraries
│  ├─ Documents
│  ├─ Sources / Connectors
│  └─ Collections
├─ Workspaces / Projects
│  ├─ Conversations
│  ├─ Saved research
│  └─ Comparisons
├─ Evaluate             [admin/engineer]
├─ Observe              [admin/engineer]
├─ Access               [admin]
│  ├─ Members
│  ├─ Groups
│  └─ Permissions
└─ Settings             [role-aware]
```

“Chat” is intentionally not the entire product hierarchy.

---

### 27.5 Global application shell

Desktop reference layout:

```text
┌─────────────────────────────────────────────────────────────────────┐
│ Org / Workspace       Global command/search           Status  User │
├──────────────┬─────────────────────────────────┬────────────────────┤
│              │                                 │                    │
│ Left rail    │ Primary working canvas          │ Evidence / Detail  │
│ 224–248 px   │ fluid                            │ rail 360–440 px    │
│              │                                 │ contextual         │
│              │                                 │                    │
└──────────────┴─────────────────────────────────┴────────────────────┘
```

Requirements:

- left navigation can collapse to an icon rail;
- right evidence rail appears only when useful and remembers width per user;
- center canvas must not shift abruptly when the evidence rail appears;
- allow keyboard resizing or accessible resize controls in addition to pointer drag;
- top-level command/search is available via `Ctrl/Cmd+K`;
- organization/workspace context remains visible at all times;
- live ingestion/query issues appear as a compact status center, not toast spam;
- page state should be deep-linkable in the URL where appropriate.

Responsive behavior:

- >= 1440 px: three-pane mode is preferred for Ask/source inspection.
- 1024–1439 px: evidence rail overlays or becomes a resizable drawer.
- 768–1023 px: navigation collapses; detail/evidence is a full-height sheet.
- < 768 px: mobile task flow; no attempt to reproduce desktop data density. Tables become list/detail or horizontally scrollable only when unavoidable.

---

### 27.6 Home — operational workspace, not a SaaS dashboard wall

The home screen answers:

1. What changed in my knowledge?
2. What needs attention?
3. What can I ask or continue?

Layout:

```text
Good morning, <name>                       [Ask anything…]

RECENT WORK                         KNOWLEDGE HEALTH
Project / conversation list         3 sources need attention
                                    1 failed sync

RECENTLY UPDATED KNOWLEDGE          SAVED / VERIFIED
Document activity feed              Authoritative collections

For admins only:
Usage / retrieval health / eval delta in a compact strip
```

Avoid a 12-card analytics grid. Operational metrics belong in Observe; Home emphasizes work continuation.

Motion:

- recent-work rows enter with a very small stagger only on first load;
- live sync status changes use layout animation and color/opacity, not bouncing elements;
- the Ask field can shared-layout-transition into the Ask workspace after submission.

---

### 27.7 Ask workspace — core RAG experience

#### 27.7.1 Empty Ask state

Do not present an enormous centered chatbot logo.

Use:

- compact title: “Ask your organization”;
- one high-quality query composer;
- visible current retrieval scope;
- recent/saved investigations;
- 3–5 context-sensitive example tasks based on available knowledge bases, not generic “summarize this document” prompts.

Composer example:

```text
┌──────────────────────────────────────────────────────────┐
│ Ask a question, compare policies, find a document…       │
│                                                          │
│ [Company ▾] [All knowledge ▾] [Attach]        [↵ Ask]   │
└──────────────────────────────────────────────────────────┘
```

Scope options can include:

- Company knowledge;
- Company + web, only if web search is enabled;
- Selected knowledge bases;
- Selected documents;
- Model-only, only if organization policy permits it.

Each scope must explain the privacy/retrieval consequence in a tooltip or secondary label.

#### 27.7.2 Active answer layout

Do not render assistant content as a rounded speech bubble.

```text
QUESTION / query title
metadata: Company knowledge · 7 sources searched · 2.1 s

Answer
──────────────────────────────────────────────
Document-like generated content with inline
citation markers [1] and structured sections.

Key evidence / table / steps when useful.

[Sources 7] [Save] [Export] [Feedback]
```

User follow-up prompts may be visually separated but should remain lightweight.

#### 27.7.3 Query stage visibility

For normal queries, expose compact real states:

```text
Searching 4 knowledge bases
   ↓
28 candidates found
   ↓
Reranking evidence
   ↓
Generating grounded answer
```

Do not expose chain-of-thought. These are system operation/status summaries only.

For fast queries, collapse stages into a single subtle status line to prevent flicker.

For slow/deep queries, show elapsed time and allow cancellation.

#### 27.7.4 Answer streaming

- Stream by semantic block/sentence where technically possible, not character-by-character typewriter simulation.
- Reserve space for the answer so surrounding controls do not jump.
- Citations must become interactive as soon as their referenced source metadata is available.
- Tables should appear as stable blocks rather than reflowing each token.
- If final citation validation changes a citation, update it visibly but without re-rendering the whole answer.

#### 27.7.5 Evidence rail

Citation click opens/updates the right rail instead of navigating away.

Evidence rail contains:

- source title;
- verified/authority state;
- source system;
- page/section;
- exact supporting passage;
- surrounding context toggle;
- document metadata permitted to the user;
- “Open document”;
- “Use only this source” follow-up action;
- “Report citation problem”.

Clicking citation `[4]` should:

1. highlight `[4]` in the answer;
2. shared-layout-transition the citation/source identity into the evidence rail header where practical;
3. scroll the supporting passage into view;
4. highlight the quote with a short non-looping emphasis animation;
5. preserve answer scroll position.

On opening the full source viewer, maintain the citation/page anchor.

#### 27.7.6 Evidence confidence presentation

Do not show invented probabilities such as “92% confident” unless properly calibrated.

Use evidence states:

- Strong support;
- Partial support;
- Conflicting sources;
- Insufficient evidence;
- Source unavailable;
- Retrieval degraded.

These states must be computed from explicit system criteria and described in product help.

#### 27.7.7 Conflicting sources

When two authoritative sources conflict, the UI should make the conflict a first-class object:

```text
⚠ Conflicting guidance found
2026 Policy Handbook — updated Sep 12
2025 Benefits FAQ — updated Mar 03

[Compare evidence]
```

The user should be able to inspect both passages side by side.

---

### 27.8 Search — separate from generative Ask

Enterprise users often know they want a file, person, clause or ticket. Do not force generation.

Search experience:

- keyword + semantic search;
- instant result list;
- query syntax/filters available but not required;
- filters for knowledge base, connector, type, author/owner, updated date, verification status, classification and metadata;
- snippets with highlighted match terms;
- semantic matches clearly distinguished from exact text hits when useful;
- keyboard up/down/enter navigation;
- preview in evidence/detail rail;
- “Ask about these results” action creates a scoped Ask session.

Search result hierarchy:

```text
Document title                                       Verified
Source / collection · updated date · owner
…highlighted matching passage…
Tags / metadata                                  Page 14
```

Result rows should be border-separated, not independent floating cards.

---

### 27.9 Knowledge library

#### 27.9.1 Default view

Use a high-quality data table, not a card grid.

Columns:

- title;
- type;
- source;
- collection/KB;
- version;
- status;
- verified/authority state;
- owner/uploader;
- classification;
- updated date;
- permissions summary;
- ingestion health.

Capabilities:

- sticky header;
- column visibility;
- sorting;
- saved filters/views;
- bulk select;
- bulk metadata changes where authorized;
- bulk reindex;
- bulk archive/delete;
- row preview without navigation;
- virtualization at large row counts;
- density toggle: comfortable/compact.

#### 27.9.2 Upload interaction

Upload must feel like a pipeline, not a spinner.

```text
employee_handbook.pdf

Uploaded       ✓
Scanning       ✓
Parsing        ✓
Chunking       438 chunks
Embedding      71%
Indexing       waiting
Permission map ✓
```

- stages update in place;
- failures expand with actionable error details;
- retry applies only to the failed/retryable stage where possible;
- user can leave the page without losing progress;
- completion sends a quiet notification/status-center entry.

Motion: progress width, check transition and row reflow only. No confetti.

---

### 27.10 Document detail and source reader

Two modes:

1. **Reader mode** for ordinary users.
2. **Inspect mode** for knowledge managers/admins.

Reader mode:

- full document/source preview;
- document outline;
- search within document;
- citation deep links;
- highlighted passage;
- metadata summary;
- verified/current-version state;
- related/referenced documents where allowed.

Inspect mode additionally shows:

- current immutable version;
- source identity and sync cursor;
- SHA-256/provenance;
- parser version/configuration;
- canonical block tree;
- chunk boundaries;
- chunk metadata;
- embedding/index generation;
- permission materialization;
- security/quarantine flags;
- ingestion run history;
- document replacement/deletion history.

Use a split-pane diff for versions. Changed paragraphs should animate into alignment only when it aids comparison.

---

### 27.11 Projects / research workspaces

A Project collects:

- selected knowledge scope;
- conversations;
- pinned evidence;
- saved searches;
- notes;
- generated reports;
- comparison tables;
- collaborators;
- activity/version history.

Project overview should look like a working dossier, not another chat history.

```text
Project: Vendor Renewal Review

Context
12 documents · Legal KB · Finance KB

Work
- Contract risk comparison
- Pricing history
- Renewal questions

Pinned evidence
- Master Agreement §4.2
- Finance approval memo

Recent activity
...
```

---

### 27.12 Compare / Matrix view

This is an important non-chat differentiator inspired by serious document-analysis products.

First-release bounded version:

- user selects 2–50 documents;
- user defines up to a limited number of comparison questions/columns;
- each row represents a document/entity;
- each generated cell contains a short result plus citations;
- cell can expand to evidence;
- export CSV/XLSX later if supported;
- run status and failed cells are independently visible;
- no hidden autonomous actions.

Example:

| Document | Termination period | Liability cap | Governing law | Risk |
|---|---|---|---|---|
| Vendor A | 30 days [1] | 1× fees [2] | Singapore [3] | Medium |
| Vendor B | 60 days [4] | Unlimited [5] | Bangladesh [6] | High |

Motion:

- column creation uses layout transition;
- completed cells fade/resolve in place;
- sorting/reordering uses Motion `layout` rather than DOM jump;
- do not animate thousands of table cells simultaneously.

---

### 27.13 Retrieval debugger — signature portfolio screen

Admin/engineer only.

The debugger must visualize the retrieval pipeline without exposing model chain-of-thought.

Layout:

```text
Query
“What changed in parental leave?”

[PLAN]      [RETRIEVE]       [RERANK]        [CONTEXT]        [ANSWER]
 filters      dense rank       new rank        selected         citations
 rewrites     lexical rank     score           token use        validation

Results inspector
┌────┬──────────┬───────┬────────┬──────────┬────────────┐
│ #  │ source   │ dense │ lexical│ reranker │ selected?  │
└────┴──────────┴───────┴────────┴──────────┴────────────┘
```

Interactions:

- hover/click a result to preview the chunk;
- toggle dense/lexical/fused result sets;
- animate rank changes using keyed `layout` transitions so the user visually understands reranking;
- show filters and permission constraints before result content;
- unauthorized documents must not appear as masked “secret results”; they must be absent;
- show latency per stage;
- show query profile, index generation, embedding model and reranker version;
- compare the trace to another RAG profile.

This page must be usable in a portfolio demo to prove that KnowledgeOS is more than a UI around an LLM API.

---

### 27.14 Evaluation lab

Primary workflow:

1. choose evaluation dataset/version;
2. select production baseline;
3. create/select candidate RAG profile;
4. run evaluation;
5. inspect aggregate delta;
6. inspect regressions;
7. promote only after gates pass.

UI:

```text
Baseline 2026-10-08       Candidate hybrid-rerank-v5

Recall@10       .914   →  .938    +.024
MRR             .781   →  .804    +.023
Citation support .921  →  .927    +.006
P95 retrieval    310ms →  362ms    +52ms
Cost/query       ...

REGRESSIONS (7)
case rows...
```

- positive aggregate metrics must not hide regressed individual cases;
- provide failure taxonomy filters;
- side-by-side evidence inspection;
- candidate promotion requires explicit confirmation and authorization;
- evaluation run status streams live;
- rank/result changes use restrained layout animations.

---

### 27.15 Observe / operations

This is where charts belong.

Sections:

- Query health;
- Retrieval latency;
- Generation latency;
- Provider errors;
- Ingestion queue and failures;
- Connector health;
- User feedback;
- Abstention rate;
- Retrieval/no-result rate;
- Citation validation failures;
- Token/provider spend;
- cache effectiveness;
- current index generation;
- latest evaluation score.

Use summary strip + trend charts + inspectable tables. Every chart should lead to the underlying traces/events.

Charts animate only on initial entry and data transition. Never use looping chart motion.

---

### 27.16 Access and permission UX

Member list:

- user;
- organization role;
- groups;
- status;
- last active;
- source identity mappings where relevant.

Permission editor:

- show inherited vs explicit access;
- explain where a permission originates;
- preview impact before removing access;
- show propagation/index update state after a change;
- do not imply a permission is effective until the backend confirms propagation.

“Access preview” must answer **which resources would be visible**, but must itself obey the administrator's authority. It must never become an indirect content-exfiltration tool.

---

### 27.17 Audit log UX

Dense event table with:

- timestamp;
- actor;
- action;
- resource;
- outcome;
- request/trace ID;
- IP/device metadata when policy permits;
- expandable structured details.

Examples:

- document uploaded;
- source synchronized;
- permissions changed;
- document deleted;
- API key created/revoked;
- RAG profile activated;
- model/privacy policy changed;
- evaluation candidate promoted.

Use monospace for IDs and machine values. Provide copy actions and deep links into related resources/traces.

---

### 27.18 Onboarding

The onboarding flow must prove value quickly while setting security correctly.

1. Create/join organization.
2. Name workspace and optionally choose company use case.
3. Create first knowledge library.
4. Choose privacy/model policy with clear explanation:
   - cloud allowed;
   - cloud with restricted providers;
   - local/private only.
5. Upload sample/real files or connect a supported source.
6. Show live ingestion pipeline.
7. Once minimum searchable content is ready, transition directly into the first Ask experience.
8. Demonstrate one citation → source jump.
9. Prompt owner/admin to invite team members only after the product has shown value.

Do not create a 12-step full-screen wizard before the user sees the product.

---

### 27.19 Public portfolio / marketing experience

Because this project is also intended to demonstrate engineering skill, the public landing page may use richer motion than the authenticated application.

#### Hero concept: “From question to evidence”

Avoid a centered glowing prompt box.

Use an interactive split composition:

```text
LEFT                                RIGHT
Enterprise knowledge               Live evidence pipeline
that can show its work.             ─────────────────────
                                    Policy_2026.pdf
Ask across documents, systems      Support_Runbook.md
and teams with permission-aware    Contract_v7.docx
retrieval and verifiable sources.       ↓ retrieve
                                         ↓ rerank
[Open demo] [View architecture]          ↓ answer + citations
```

On first viewport interaction, a sample query can travel through source rows and resolve into evidence/answer blocks. This is a visual metaphor only; it must not misrepresent actual processing.

#### Landing page sections

1. Hero / live product preview.
2. Source-grounded answer with interactive citation transition.
3. Hybrid retrieval visualized as exact + semantic results merging.
4. Permission-aware architecture.
5. Document ingestion lifecycle.
6. Retrieval debugger preview.
7. Evaluation before/after comparison.
8. Local/cloud model routing.
9. Architecture diagram / technical stack.
10. Security/observability capabilities.
11. GitHub/demo call to action.

Use scroll-triggered motion sparingly to explain architecture. Never make users scroll through a cinematic sequence to access content.

---

### 27.20 Motion system — Motion.dev implementation specification

Motion is an interaction layer, not decoration.

#### 27.20.1 Core Motion APIs to use

- `motion.*` for state transitions and gestures;
- `layout` for reflowing panels, rows, filters and ranked results;
- `layoutId` for citation → evidence and card/detail shared-element relationships;
- `AnimatePresence` for drawers, transient panels, filters, source previews and mode changes;
- `whileHover`, `whileTap`, `whileFocus` for tactile controls where CSS is insufficient;
- variants for coordinated state transitions;
- `stagger()` only for small groups and first-entry sequences;
- `useScroll`/scroll-triggered effects primarily for the public landing page;
- `useReducedMotion` plus global `MotionConfig reducedMotion="user"`;
- `layoutScroll` on animated elements inside scroll containers when required.

#### 27.20.2 Motion tokens

Reference durations:

```ts
export const duration = {
  instant: 0.08,
  fast: 0.14,
  base: 0.20,
  deliberate: 0.28,
  panel: 0.34,
}

export const ease = {
  standard: [0.22, 1, 0.36, 1],
  enter: [0.16, 1, 0.3, 1],
  exit: [0.4, 0, 1, 1],
}
```

These are design tokens and must be tested on real hardware.

Guidelines:

- button feedback: 80–140 ms;
- menus/tooltips: 120–180 ms;
- tab/selection indicator: 160–220 ms;
- panel/drawer: 220–340 ms;
- shared-element source transition: 240–360 ms;
- page-level authenticated-app transition: usually opacity/layout <= 220 ms; avoid cinematic routes;
- marketing story transitions may extend to ~500–700 ms only when user-controlled/scroll-linked.

#### 27.20.3 Shared layout transitions

High-value uses:

- Home Ask field → Ask workspace composer;
- active navigation underline/selection;
- document row → preview/detail header;
- citation marker/source chip → evidence rail source header;
- compact ingestion item → expanded diagnostics;
- retrieval rank before → after reranking;
- selected evaluation case → side-by-side inspector.

Do not assign `layout` to every component. Use it only where spatial continuity adds understanding.

#### 27.20.4 Enter/exit transitions

Use `AnimatePresence` for:

- evidence drawer;
- command palette;
- filter popovers;
- source preview;
- notices/errors;
- compare-cell expansion;
- trace details.

Default entrance should be opacity + <= 6–10 px translation. Large-scale zoom effects should be rare.

#### 27.20.5 List/rank transitions

When retrieval results reorder:

- rows keep stable keys;
- `layout="position"` or equivalent layout transition moves rows to new rank;
- changed score can crossfade;
- newly selected context receives one brief border/background emphasis;
- animation is disabled when item count exceeds a safe threshold or reduced motion is enabled.

This is particularly useful in the Retrieval Debugger because motion explains what reranking actually did.

#### 27.20.6 Loading and system activity

Loading animation must answer “what is happening?”

Preferred:

- semantic skeleton for initial page data;
- query stage text/status;
- linear/segmented progress for deterministic jobs;
- subtle indeterminate bar only when progress is unknowable;
- inline spinner for tiny local operations;
- job list for long asynchronous work.

Avoid:

- fake progress resetting to zero;
- endless sparkle loops;
- looping blobs;
- artificial typewriter delays.

#### 27.20.7 Gestures

Desktop:

- hover may reveal row actions and source previews;
- click/tap feedback uses very small scale/opacity changes;
- drag permitted for pane resize and optional document ordering only when keyboard alternative exists.

Touch:

- no hover-dependent essential feature;
- swipe should not conflict with browser navigation;
- minimum target sizes follow accessibility guidance.

#### 27.20.8 Scroll motion

Authenticated app:

- almost none beyond sticky/header state and subtle in-view loading;
- no parallax in working surfaces.

Public landing page:

- `whileInView` for architecture sections;
- `useScroll` for a retrieval-flow progress line or source-to-answer demonstration;
- transforms must remain subtle and disable under reduced motion.

#### 27.20.9 Reduced motion

At the app root:

```tsx
<MotionConfig reducedMotion="user">
  {children}
</MotionConfig>
```

For users preferring reduced motion:

- replace large x/y movement with fades;
- disable parallax;
- disable animated rank travel and update rows instantly or crossfade;
- preserve meaningful state-change feedback;
- never hide information because animation is disabled.

#### 27.20.10 Motion performance budget

- Target smooth interaction on a normal mid-range laptop, not only a high-end GPU.
- Prefer transform and opacity.
- Do not animate `box-shadow`, blur or large backdrop-filter regions continuously.
- Avoid layout animation across huge virtualized lists.
- Virtualized table rows should not all mount Motion components unless profiling shows it is safe.
- Lazy-load heavy source viewers/charts.
- Measure animation in Performance panel and with Motion performance tooling where useful.
- No animation may block text input, source opening or query cancellation.

---

### 27.21 Interaction details that make the product feel “smart”

#### Command palette

`Cmd/Ctrl+K` searches:

- pages;
- documents;
- knowledge bases;
- projects;
- recent queries;
- admin actions allowed to the current role.

Results update without flashy animation; selected item uses shared active-indicator motion.

#### Contextual command menu

Selecting text in an answer/source may offer:

- Ask about selection;
- Pin evidence;
- Copy with citation;
- Open in source;
- Compare with…

This should be a small contextual menu, not an always-visible toolbar.

#### Citation hover

Desktop citation hover after a short delay shows a small evidence preview. Clicking opens persistent evidence rail. Mobile skips hover preview.

#### Copy behavior

“Copy answer” should support:

- plain text;
- Markdown;
- text with citations;
- selected section only.

#### Saved investigations

Users can title/save an Ask thread or Project. Save state transitions from outline → filled indicator with no celebratory animation.

#### Keyboard shortcuts

Minimum:

- `Cmd/Ctrl+K`: command/search;
- `/`: focus Ask/search where safe;
- `Esc`: close evidence/overlay;
- `Cmd/Ctrl+Enter`: submit where multiline composer uses Enter for newline;
- `[` / `]` optional previous/next citation when evidence rail is focused;
- arrow-key table/list navigation where accessible.

Shortcuts must have discoverable labels and must not override browser/assistive-tech conventions recklessly.

---

### 27.22 Empty, error and degraded states

Every major screen needs intentional states.

#### Empty knowledge base

Explain exactly what will happen after a file/source is added. Primary action: Add knowledge.

#### No retrieval result

Say that sufficient evidence was not found. Offer:

- broaden scope;
- remove filters;
- search instead of generate;
- inspect selected sources;
- ask an admin if access may be missing.

Never fabricate an answer to avoid an empty state.

#### Partial provider outage

Show a compact degradation banner such as:

- “Reranking unavailable; using fused retrieval ordering.”
- “Cloud generation unavailable. Local generation is active.”

Do not expose stack traces to ordinary users.

#### Permission propagation

After access changes:

```text
Permission saved
Updating searchable access…
✓ Search index confirmed at 14:32:09
```

Until confirmation, the admin UI must not falsely state that propagation has completed.

#### Ingestion failure

Display stage, safe error explanation, retryability and support trace ID.

---

### 27.23 Toast and notification policy

Use toast only for short-lived confirmation that does not require later attention.

Use status center/inbox for:

- ingestion failure;
- connector failure;
- long evaluation complete;
- index-generation build complete;
- security/admin warning.

Do not show duplicate toast + banner + notification for the same event.

---

### 27.24 Accessibility requirements

Minimum acceptance requirements:

- WCAG 2.2 AA target;
- full keyboard access;
- visible focus state;
- logical DOM/source order independent of visual panes;
- correct headings/landmarks;
- ARIA only where native elements are insufficient;
- accessible names on icon-only controls;
- status changes announced through appropriate live regions without reading every streamed token;
- color is never the only status signal;
- charts have text/table alternatives;
- modal/drawer focus trapping and restoration;
- skip links;
- zoom to 200% without loss of critical functionality;
- reduced-motion support via Motion;
- source citations usable with keyboard and screen readers;
- table semantics preserved even when virtualization is used.

Streaming answers need special handling: do not continuously interrupt screen-reader users with every token. Announce major state changes and provide the final answer as normal document content.

---

### 27.25 Frontend performance budgets

Initial targets for production build, measured and adjusted realistically:

- Core app route should become interactive quickly on normal broadband/mid-range hardware.
- Keep initial JavaScript route-specific; admin/debug tooling must not inflate ordinary employee Ask bundle.
- Lazy-load PDF viewer, evaluation charts, retrieval debugger and heavy editors.
- Image assets use responsive sizing and modern formats.
- Avoid loading all connector logos/fonts on first paint.
- Long document lists and audit logs use server pagination/cursoring plus virtualization where appropriate.
- Long conversations virtualize older turns if profiling requires it without breaking search/citation anchors.
- Streaming updates are batched enough to avoid re-rendering the entire answer tree for every token.
- Motion usage is profiled; use CSS transitions for trivial color/background changes when Motion adds no value.

Track:

- LCP;
- INP;
- CLS;
- route JS size;
- hydration time;
- long tasks;
- Ask composer input latency during streaming;
- source viewer open latency.

---

### 27.26 Frontend state architecture

Separate state categories explicitly.

#### Server state

TanStack Query:

- organizations;
- knowledge bases;
- documents;
- connector state;
- permissions;
- conversations;
- evaluations;
- traces;
- metrics.

#### URL state

Use URL/search params for shareable state:

- active KB/project;
- search query/filter;
- selected document;
- citation/page anchor;
- evaluation run/case;
- debugger trace.

#### Local UI state

Keep local where possible:

- evidence drawer open/width;
- local table density;
- command palette;
- selected temporary rows;
- unsaved composer draft.

Do not introduce a global client store until a concrete cross-tree state problem justifies it.

#### Streaming state

Create a dedicated answer-stream reducer/state machine handling events such as:

```text
query.accepted
retrieval.started
retrieval.completed
rerank.started
rerank.completed
generation.started
answer.delta
citation.available
answer.completed
answer.failed
query.cancelled
```

This prevents ad-hoc booleans such as `isLoading`, `isStreaming`, `isSearching`, `isThinking` from becoming inconsistent.

---

### 27.27 Component architecture

Suggested frontend domains:

```text
apps/web/
├─ app/
├─ components/
│  ├─ primitives/          # restyled Radix/shadcn base
│  ├─ shell/
│  ├─ motion/
│  ├─ command/
│  ├─ tables/
│  └─ feedback/
├─ features/
│  ├─ ask/
│  │  ├─ composer/
│  │  ├─ answer/
│  │  ├─ citations/
│  │  └─ evidence/
│  ├─ search/
│  ├─ knowledge/
│  ├─ documents/
│  ├─ ingestion/
│  ├─ projects/
│  ├─ compare/
│  ├─ evaluation/
│  ├─ debugger/
│  ├─ observe/
│  ├─ access/
│  └─ audit/
├─ lib/
│  ├─ api/
│  ├─ auth/
│  ├─ events/
│  ├─ motion/
│  ├─ permissions/
│  └─ validation/
└─ styles/
   ├─ tokens.css
   └─ globals.css
```

Motion primitives should be centralized enough that timing/easing/reduced-motion policy remains consistent.

---

### 27.28 Design token implementation

Create token layers rather than hard-coded Tailwind values throughout feature code.

Required groups:

- color;
- typography;
- spacing;
- radius;
- border;
- elevation;
- motion duration/ease/spring;
- z-index;
- pane dimensions;
- control heights;
- density modes.

Example semantic spacing/control tokens:

```text
control-sm: 28
control-md: 34
control-lg: 40
sidebar-expanded: 236
sidebar-collapsed: 64
evidence-default: 400
reading-max: 780
```

Exact pixel values should be adjusted through implementation testing, but semantic names must remain stable.

---

### 27.29 Frontend testing strategy

#### Unit/component

Test:

- answer stream reducer/state machine;
- citation parsing/mapping;
- permission-driven component visibility;
- filter/query serialization;
- source scope selection;
- error/degraded-state rendering;
- reduced-motion branches;
- document pipeline status mapping.

#### Accessibility

Automated axe checks on major routes plus manual keyboard/screen-reader smoke tests.

#### Visual regression

Capture at least:

- light/dark;
- normal/reduced motion end states;
- empty/loading/error/populated;
- 1440 desktop;
- 1024 compact;
- representative mobile width.

#### Playwright E2E critical journeys

1. login → Ask → citation → source page;
2. search → preview → scope Ask to selected results;
3. upload → ingestion progress → searchable document;
4. replace document → new version active;
5. permission removal → affected user can no longer search/retrieve;
6. retrieval debugger → inspect rerank result;
7. evaluation baseline/candidate → inspect regression;
8. connector failure → admin sees actionable status;
9. keyboard-only Ask and citation navigation;
10. reduced-motion user sees functionally equivalent transitions.

#### Motion tests

Avoid brittle tests asserting exact animation frames. Test:

- resulting state;
- element presence/removal;
- focus restoration;
- reduced-motion behavior;
- no interaction blocked during animation.

---

### 27.30 Frontend implementation phases

#### FE-0 — design foundation

Deliver:

- token sheet;
- typography;
- light/dark palettes;
- icon rules;
- spacing/radius/elevation;
- Motion tokens;
- 10–15 core primitives;
- Storybook or equivalent component preview if project overhead is acceptable.

Exit gate:

- no default shadcn styling visible;
- accessibility/focus states established;
- reduced-motion policy works.

#### FE-1 — application shell

Deliver:

- authenticated shell;
- nav rail;
- org/workspace switcher;
- command palette;
- evidence panel container;
- responsive behavior;
- route transitions.

Exit gate:

- keyboard navigation and responsive pane behavior pass.

#### FE-2 — Knowledge + ingestion

Deliver:

- library table;
- filters;
- document detail reader;
- upload pipeline;
- ingestion diagnostics;
- source/connector status.

Exit gate:

- user can upload and inspect a document lifecycle without reading backend logs.

#### FE-3 — Search

Deliver:

- instant search;
- faceted filters;
- source preview;
- selected-result scoping;
- keyboard navigation.

Exit gate:

- exact identifier and semantic queries are both understandable from the UI.

#### FE-4 — Ask + evidence

Deliver:

- composer;
- scope control;
- stage stream;
- answer renderer;
- inline citations;
- evidence rail;
- source deep link;
- feedback;
- abstention/conflict/degraded states.

Exit gate:

- citation-to-source experience works reliably for PDF and at least one non-PDF source type.

#### FE-5 — Projects + comparison

Deliver:

- saved investigation/project;
- pinned evidence;
- bounded Compare/Matrix flow;
- project activity.

Exit gate:

- cross-document work no longer depends solely on conversational history.

#### FE-6 — Admin / access / audit

Deliver:

- members/groups;
- permission editor;
- propagation status;
- audit log;
- model/privacy policy controls.

Exit gate:

- security-sensitive state is explicit and backend-confirmed.

#### FE-7 — Retrieval debugger + evaluation

Deliver:

- pipeline stepper;
- rank visualization;
- chunk inspector;
- profile/index metadata;
- baseline/candidate evaluation comparison;
- regression inspector.

Exit gate:

- a reviewer can diagnose a bad answer from the UI.

#### FE-8 — Observe

Deliver:

- query/retrieval/provider/ingestion health;
- cost/tokens;
- feedback and abstention;
- trace drill-down.

Exit gate:

- charts are linked to inspectable underlying data.

#### FE-9 — portfolio landing/demo

Deliver:

- non-generic marketing page;
- live or deterministic demo data;
- architecture/retrieval visualization;
- Motion-based evidence flow;
- GitHub/architecture links.

Exit gate:

- Lighthouse/accessibility/performance review;
- no misleading fake AI processing;
- reduced-motion landing behavior complete.

#### FE-10 — refinement

Perform:

- animation/performance profiling;
- bundle splitting;
- accessibility audit;
- visual regression review;
- copy/terminology cleanup;
- density tuning with realistic data volumes;
- mobile task-flow testing;
- remove any animation that does not improve comprehension.

---

### 27.31 Frontend definition of done

Frontend is not complete until all of these are true:

- the product is visually distinct from generic AI chatbot templates;
- ordinary users can Ask, Search and inspect evidence without understanding RAG terminology;
- citations reach exact source context in <= 2 interactions;
- Search remains useful without invoking generation;
- long-form answers are readable as documents rather than chat bubbles;
- document/knowledge administration works efficiently with hundreds/thousands of rows;
- ingestion state is visible and recoverable;
- permission changes show propagation state;
- admin retrieval behavior can be debugged visually;
- baseline/candidate RAG quality can be compared visually;
- all essential workflows work with keyboard only;
- reduced-motion mode remains fully functional;
- motion remains smooth under normal streaming/query load;
- heavy admin screens are code-split away from the core Ask experience;
- no critical frontend accessibility issues remain;
- no animation exists solely to signal “this is AI”.

---

## 28. Security architecture

Create a formal `docs/threat-model/THREAT_MODEL.md` before calling the system production-ready.

### 28.1 Threats to cover

- cross-tenant data leakage;
- IDOR/broken object-level authorization;
- stale document permissions;
- prompt injection in retrieved documents;
- poisoned documents/index entries;
- malicious file uploads;
- parser vulnerabilities;
- SSRF through web/connectors;
- XSS through model-generated Markdown or source text;
- SQL injection;
- credential/API-key leakage;
- connector-token theft;
- cache leakage;
- retrieval probing/reconnaissance;
- excessive LLM-cost abuse;
- denial of service with large files/queries;
- provider outage;
- supply-chain dependency compromise;
- deleted data remaining in embeddings/cache;
- accidental external-provider use for local-only data.

### 28.2 Required controls

**Authentication**
- OIDC validation;
- short-lived access tokens;
- secure session/cookie settings on frontend;
- CSRF controls where cookie-backed state is used.

**Authorization**
- permission checks in service layer;
- tenant RLS;
- chunk ACL metadata;
- retrieval-time ACL filtering;
- admin endpoint scopes.

**Uploads**
- quarantine;
- MIME verification;
- malware scan;
- parser sandbox/resource limits;
- no macro execution;
- object-size limits.

**Prompt injection**
- trust delimiters;
- source scanning;
- no tool execution from evidence;
- system-instruction reinforcement;
- bounded evidence size;
- red-team corpus.

**Web safety**
- sanitized Markdown renderer;
- block `javascript:` and unsafe schemes;
- appropriate CSP;
- secure headers/HSTS in production;
- strict CORS allowlist.

**Secrets**
- environment variables only in local development;
- production secret manager;
- connector OAuth tokens encrypted with KMS/provider key management;
- rotate secrets;
- no secrets in logs.

**Rate/abuse limits**
- per-user query rate;
- per-org aggregate rate;
- upload size/count limits;
- connector crawl limits;
- token/cost budgets.

**Audit**
- append-only logical event stream;
- permission changes always audited;
- index/profile/model-policy activation audited.

### 28.3 External model privacy policy

Every generation/embedding/reranking call is checked against KB model policy and document classification before content leaves the deployment boundary.

Do not rely on UI settings alone; enforce policy in backend provider routing.

---

## 29. Deletion and retention

Deleting a source/document must propagate through all derived systems.

Deletion workflow:

1. mark document non-retrievable immediately;
2. create deletion outbox event;
3. remove chunks/embeddings from all active/candidate index generations as policy requires;
4. invalidate derived parser/chunk artifacts according to retention policy;
5. invalidate any response/retrieval cache entries;
6. remove source binary after retention/legal-hold rules allow;
7. retain only the minimum audit tombstone required by policy;
8. run a verification query/job proving no active chunk remains;
9. log deletion completion.

Periodic orphan sweeper checks:

- chunks with missing/deleted document versions;
- active index chunks from inactive document versions;
- source objects deleted upstream but still indexed;
- expired cache/artifacts.

---

## 30. Caching policy

Use caching conservatively because RAG caches can leak data.

Safe/useful initial caches:

- embedding cache keyed by exact model/version + text hash, tenant scoped;
- parsed canonical artifact cache through object storage;
- provider/model metadata cache;
- JWKS cache;
- short-lived configuration cache.

Avoid full-answer caching in v1.

If retrieval/answer caching is later enabled, key it by at least:

- organization;
- KB;
- active index-generation revision;
- effective principal/ACL signature;
- query;
- RAG profile version;
- model version;
- explicit filters.

Any permission/document/index change must invalidate affected entries.

---

## 31. Observability

### 31.1 Trace structure

Create one root trace per query.

Child spans:

```text
auth
query.normalize
query.rewrite
query.embed
search.vector
search.lexical
search.fusion
search.rerank
context.pack
llm.generate
citation.validate
persist
```

For ingestion:

```text
upload.verify
malware.scan
parse
normalize
security.scan
chunk
embed
index
verify
```

### 31.2 Trace attributes

Include safe metadata:

- request/query ID;
- organization ID (hashed or controlled where appropriate);
- KB ID;
- index generation;
- RAG profile version;
- provider/model;
- candidate counts;
- selected chunk IDs;
- latency;
- token usage;
- estimated cost;
- degraded-mode flags;
- error code.

Do not put raw sensitive source text into infrastructure metric labels.

### 31.3 Service metrics

- request count/error rate;
- P50/P95/P99 latency;
- retrieval/reranker/model latency;
- ingestion throughput/failure rate;
- queue depth/oldest job age;
- connector sync success/failure;
- vector/lexical result counts;
- abstention rate;
- feedback up/down ratio;
- rate-limit events;
- token/cost by provider/model/org;
- database pool saturation;
- Redis availability;
- object-store errors.

### 31.4 Alerts

At minimum:

- API error-rate spike;
- queue backlog too old;
- ingestion failure spike;
- database unavailable/high saturation;
- provider error spike;
- source-sync repeated failure;
- evaluation security regression;
- unusual authorization-denied spike/reconnaissance pattern;
- cost threshold exceeded.

---

## 32. Evaluation framework

A RAG system is not complete until retrieval and answer quality are versioned and measurable.

### 32.1 Golden dataset schema

Each case should store:

- `case_id`;
- organization/KB fixture;
- principal/user fixture;
- query;
- query type;
- language;
- expected answer/facts;
- expected relevant document IDs;
- optional relevant chunk IDs;
- expected citation requirements;
- expected answerability (`answer`, `abstain`, `access_denied`);
- metadata filters;
- difficulty/category tags;
- human notes.

### 32.2 Initial 200-case target

A balanced starting set:

- 50 straightforward factual questions;
- 30 exact identifier/policy-code questions;
- 30 paraphrased semantic questions;
- 20 cross-document comparisons;
- 20 unanswerable/abstention questions;
- 20 authorization/tenant-isolation cases;
- 15 multilingual/cross-lingual cases;
- 15 adversarial/prompt-injection/poisoning cases.

Synthetic question generation may bootstrap candidates, but a human must review the golden set.

### 32.3 Retrieval metrics

- Recall@K;
- Precision@K;
- Hit Rate@K;
- MRR;
- nDCG;
- relevant-document recall;
- duplicate rate;
- authorized-retrieval violation count.

### 32.4 Generation metrics

- factual correctness;
- answer relevance;
- faithfulness/groundedness;
- context precision/recall where applicable;
- citation precision/support;
- citation completeness;
- abstention accuracy;
- contradiction handling.

### 32.5 Operational metrics

- retrieval latency;
- reranker latency;
- time to first token;
- total latency;
- input/output tokens;
- cost/query;
- context tokens;
- provider failures.

### 32.6 Security metrics/tests

Hard gate:

- cross-tenant leakage = 0;
- unauthorized chunk selection = 0;
- revoked document still searchable = 0;
- deleted document still searchable = 0;
- poisoned source overriding system policy = 0 accepted red-team successes;
- local-only KB external-provider calls = 0.

### 32.7 Evaluation execution modes

**PR smoke evaluation**
- ~20–30 deterministic/high-signal cases;
- runs on changes to RAG pipeline/prompt/search code.

**Full offline evaluation**
- 200+ cases;
- before activating a new RAG profile/index generation/model.

**Nightly/periodic evaluation**
- detects regressions from dependencies/providers/data changes.

**Online evaluation**
- sample production traces according to privacy policy;
- use feedback and automatic evaluators;
- route failures to an annotation queue.

### 32.8 Avoiding evaluator traps

- Do not depend solely on LLM-as-judge.
- Keep deterministic retrieval/security metrics.
- Version evaluator prompts/models.
- Periodically human-review random samples and disagreement cases.
- Store evaluation artifacts with git SHA and exact configuration.

---

## 33. RAG experiment matrix

Run experiments rather than guessing.

### Retrieval experiments

- dense only vs lexical only vs hybrid;
- fusion weights;
- dense K / lexical K;
- exact-identifier boost;
- query rewrite on/off;
- parent-child vs flat chunks;
- chunk size/overlap;
- neighbor expansion;
- model A vs model B embeddings;
- local vs cloud reranker;
- final context K/token budget.

### Promotion rule

A candidate is promoted only if:

- security gates still pass;
- target quality improves or remains acceptable;
- latency/cost regression is within documented budget;
- no major category becomes materially worse without explicit acceptance.

Keep baseline and candidate results side-by-side.

---

## 34. Reliability and failure handling

### 34.1 Timeouts

Every external dependency has explicit connect/read/total timeouts.

### 34.2 Retry policy

Retry only operations safe to retry or protected by idempotency.

Use:

- exponential backoff;
- jitter;
- max attempts;
- retryable error classification.

### 34.3 Circuit breakers/degraded mode

Provider outages should not cause uncontrolled request pileup.

Examples:

- reranker unavailable -> optionally fused-search mode;
- generation provider unavailable -> allowed fallback or return retrieved sources/search results;
- vector backend unavailable -> lexical-only if policy permits;
- ACL/database unavailable -> **fail closed**.

### 34.4 Transactional outbox

Use transactional outbox for events where a DB change must reliably lead to background work:

- ingestion requested;
- document delete;
- permission propagation;
- connector sync requested;
- index generation activation cleanup.

This prevents “DB committed but queue publish failed” gaps.

### 34.5 Backups/disaster recovery

Production profile:

- automated PostgreSQL backups/PITR where hosting supports it;
- object-store versioning or lifecycle-controlled backup;
- documented Redis as non-authoritative/replaceable;
- infrastructure/configuration stored in code;
- restore runbook;
- periodic restore drill.

The vector index must be reconstructable from canonical documents/chunks, but backups shorten recovery time.

---

## 35. Cost and quota controls

Track every provider call:

- provider;
- model;
- input tokens;
- output tokens;
- embedding units/tokens;
- reranker calls;
- current pricing-table version/estimated cost.

Controls:

- org monthly soft budget;
- optional hard budget;
- per-user rate limit;
- per-org concurrency limit;
- max query length;
- max evidence tokens;
- max upload size/pages;
- connector page/document caps;
- max retry attempts.

Admin analytics should expose cost by:

- organization;
- KB;
- user/service account;
- provider/model;
- day/month.

---

## 36. Performance plan

### 36.1 Reference scale tests

Maintain two benchmark profiles:

**Developer benchmark**
- 10k–50k chunks;
- local Docker stack;
- verifies correctness/latency trends.

**Portfolio production benchmark**
- at least 100k chunks, preferably a synthetic/realistic path toward 1M;
- separate retrieval-only load test from expensive full LLM test;
- multiple organizations and ACL patterns.

### 36.2 Load tests

Use Locust or k6.

Test:

- search-only QPS;
- full RAG concurrency;
- simultaneous uploads;
- connector sync while users query;
- permission updates during query load;
- document deletion/reindex under load.

Track:

- latency percentiles;
- DB CPU/IO;
- pool saturation;
- Redis latency;
- HNSW behavior;
- worker queue depth;
- model GPU/CPU utilization for local inference.

### 36.3 Scaling sequence

Do not jump directly to a distributed vector database.

1. tune SQL/indexes;
2. add HNSW iterative scans/appropriate parameters;
3. scale PostgreSQL resources/read patterns;
4. batch provider calls;
5. scale API/workers horizontally;
6. isolate local model serving;
7. only then move the `SearchBackend` implementation if measured requirements demand it.

---

## 37. CI/CD

### 37.1 Pull request pipeline

Backend:

1. dependency install/lock verification;
2. Ruff;
3. type checking;
4. unit tests;
5. integration tests using Postgres/Redis/MinIO containers;
6. migration test from previous schema;
7. security/static scans;
8. RAG smoke evaluation when relevant files changed.

Frontend:

1. install locked dependencies;
2. lint;
3. typecheck;
4. unit/component tests;
5. build.

Cross-stack:

- API contract/OpenAPI drift test;
- Playwright critical E2E;
- Gitleaks;
- container build;
- Trivy scan;
- SBOM generation.

### 37.2 Deployment pipeline

Recommended:

```text
PR checks
  ↓
merge main
  ↓
build immutable images
  ↓
deploy staging
  ↓
migrations
  ↓
smoke tests
  ↓
security/RAG evaluation subset
  ↓
manual or policy promotion
  ↓
production
  ↓
post-deploy synthetic queries
```

### 37.3 Migration discipline

Use expand/migrate/contract for risky DB changes:

1. additive schema;
2. deploy code compatible with old/new;
3. backfill;
4. switch reads/writes;
5. later remove old schema.

Never combine irreversible destructive migration and untested application change in one step.

---

## 38. Deployment profiles

### 38.1 Local development

Docker Compose:

- PostgreSQL + pgvector;
- Redis;
- MinIO;
- Keycloak;
- Mailpit if invitation mail is implemented;
- optional Langfuse/local model profiles.

API/web can run on host for fast development.

### 38.2 Portfolio/demo deployment

Keep operating cost manageable:

- Next.js on a managed frontend host;
- FastAPI API + workers on Render/Fly/Railway-like compute;
- managed PostgreSQL with pgvector;
- managed Redis;
- R2/S3-compatible storage;
- managed OIDC provider or hosted Keycloak;
- Langfuse cloud/self-host based on budget/privacy.

### 38.3 Enterprise reference deployment

Document but do not require the portfolio demo to pay for all components:

- containerized API/workers on ECS/Kubernetes equivalent;
- managed PostgreSQL/RDS-style service;
- managed Redis;
- S3-compatible storage;
- KMS;
- WAF/load balancer;
- secret manager;
- private networking;
- autoscaling;
- centralized logs/metrics/traces;
- backup/PITR.

Terraform should describe at least one reproducible production-style environment by the end of the project.

---

## 39. Testing strategy

### 39.1 Unit tests

Cover:

- permission resolution;
- query filter validation;
- RRF fusion;
- context-budget packing;
- citation alias parser;
- chunker boundary logic;
- model-policy routing;
- deletion state transitions;
- pricing/cost calculation;
- source sync diffing.

### 39.2 Integration tests

Real PostgreSQL/pgvector, Redis and object storage:

- tenant RLS;
- vector search with filters;
- lexical search;
- hybrid fusion;
- ACL filtering;
- upload -> worker -> indexed document;
- replace version;
- permission change propagation;
- deletion propagation;
- transactional outbox delivery;
- retry/idempotency.

### 39.3 End-to-end tests

Playwright critical journeys:

1. sign in;
2. create org/KB;
3. upload document;
4. wait for READY;
5. ask question;
6. open citation;
7. create restricted document;
8. verify permitted user sees it;
9. verify unauthorized user does not;
10. replace/delete document;
11. confirm retrieval changes.

### 39.4 Security regression tests

Mandatory cases:

- Org A vs Org B cross-tenant query;
- IDOR document URL/API attempt;
- restricted document exact-title probing;
- permission revoked after embedding;
- deleted document search;
- poisoned text “ignore previous instructions”;
- hidden Unicode instruction;
- malicious Markdown/XSS output;
- SSRF crawler request to local/private address;
- zip/decompression bomb fixture;
- overlarge file;
- leaked cache key attempt;
- local-only KB monitored for external provider calls;
- prompt asks model to reveal inaccessible documents;
- source citation ID tampering.

### 39.5 Failure/chaos tests

- kill worker mid-ingestion then recover;
- Redis restart;
- object-store timeout;
- LLM timeout;
- embedding provider timeout;
- reranker timeout;
- DB transient connection failure;
- duplicate outbox delivery;
- connector returns same revision twice.

---

## 40. Detailed implementation phases

Each phase has an exit gate. Do not move past a gate with broken fundamentals.

### Phase 0 — Architecture and repository foundation

**Build**
- monorepo;
- backend/frontend skeleton;
- Dockerfiles;
- Docker Compose;
- configuration system;
- logging/request IDs;
- Alembic;
- CI skeleton;
- architecture decision records.

**ADRs to write**
- ADR-001 modular monolith;
- ADR-002 PostgreSQL/pgvector-first search;
- ADR-003 OIDC identity;
- ADR-004 tenant RLS strategy;
- ADR-005 async ingestion/outbox;
- ADR-006 provider abstraction;
- ADR-007 index generations.

**Exit gate**
- API, web, Postgres, Redis and object storage run locally;
- CI green;
- first migration reproducible.

### Phase 1 — Authentication, organizations and authorization

**Build**
- OIDC login flow;
- JWT verification;
- users/orgs/memberships;
- roles/permissions;
- groups;
- RLS middleware/session context;
- org/KB authorization helpers;
- audit events for admin changes.

**Tests**
- tenant isolation;
- unauthorized object access;
- role permissions.

**Exit gate**
- two test organizations cannot read each other through API or direct repository calls.

### Phase 2 — Knowledge bases, uploads and object storage

**Build**
- KB CRUD/access;
- upload presign/finalize flow;
- quarantine storage;
- document/version models;
- file validation;
- SHA-256;
- ingestion job state UI.

**Exit gate**
- valid file produces durable document version + queued job;
- malicious/unsupported fixtures fail safely.

### Phase 3 — Reliable ingestion engine

**Build**
- outbox dispatcher;
- Celery worker;
- Docling adapter;
- canonical artifact;
- OCR path;
- security scanner;
- chunking;
- progress/events;
- retry/reconciliation.

**Exit gate**
- all core formats parse into canonical artifacts;
- worker restart does not duplicate final chunks;
- failed jobs are diagnosable and retryable.

### Phase 4 — Indexing and retrieval-only search

**Build**
- index generation model;
- 1024-d embeddings;
- `tsvector` indexing;
- HNSW;
- ACL tokens on chunks;
- dense search;
- lexical search;
- RRF fusion;
- `/search` endpoint;
- retrieval debugger initial UI.

**Exit gate**
- exact identifiers and semantic queries both work;
- restricted chunks are never returned;
- active generation constraint is enforced.

### Phase 5 — Reranking, context and grounded generation

**Build**
- reranker provider;
- context packer;
- source aliasing;
- LLM provider;
- grounded system prompt;
- abstention;
- citation validation;
- SSE streaming;
- source panel/PDF page link.

**Exit gate**
- every successful business answer has valid source aliases;
- no-answer fixture abstains;
- poisoned retrieval fixture cannot override system policy.

### Phase 6 — Conversation UX and advanced query routing

**Build**
- conversations/messages;
- history-aware rewrite;
- query-type router;
- comparison decomposition;
- document summary path;
- exhaustive-query guardrails.

**Exit gate**
- follow-up questions remain grounded;
- permission change between turns is respected.

### Phase 7 — Evaluation platform

**Build**
- dataset schema;
- 200-case initial golden set;
- retrieval metrics;
- Ragas/other generation metrics;
- security hard gates;
- experiment runner;
- evaluation lab UI;
- candidate-vs-baseline report.

**Exit gate**
- every RAG profile change can produce reproducible metrics;
- security failures block promotion.

### Phase 8 — Observability, feedback and cost controls

**Build**
- OTel spans;
- Langfuse/equivalent tracing;
- service metrics;
- admin analytics;
- user feedback;
- usage/cost ledger;
- quotas/rate limits;
- alert definitions.

**Exit gate**
- a bad answer can be traced from user query through selected evidence and model response;
- model/provider costs visible.

### Phase 9 — Document lifecycle and zero-downtime reindexing

**Build**
- replace/version flow;
- index candidate build;
- evaluation gate;
- atomic generation activation;
- rollback;
- document archive/delete cascade;
- orphan sweeper;
- deletion verification job.

**Exit gate**
- old document is no longer retrieved after replacement/retirement;
- deleted chunks cannot be found;
- index-generation rollback works.

### Phase 10 — Connectors and permission synchronization

**Build**
- connector interface;
- website/sitemap connector;
- one enterprise document connector (Google Drive recommended for portfolio usability);
- sync cursors;
- change/delete detection;
- source permission synchronization;
- connector health UI.

**Exit gate**
- changed/deleted/repermissioned source data propagates correctly.

### Phase 11 — Local/cloud model policy

**Build**
- local embedding endpoint;
- local reranker;
- local generation adapter;
- model-policy UI;
- external-provider enforcement by classification/KB;
- fallback policy;
- provider health metrics.

**Exit gate**
- local-only KB produces **zero** external model-provider requests in automated test.

### Phase 12 — Security hardening

**Build**
- formal threat model;
- SSRF protection;
- XSS/CSP hardening;
- API-key scopes;
- connector token encryption;
- rate/abuse rules;
- security dashboards;
- red-team dataset;
- dependency/container scanning.

**Exit gate**
- mandatory security regression suite passes;
- no unresolved critical/high finding accepted for release.

### Phase 13 — Performance/resilience

**Build/test**
- realistic dataset generator;
- 100k+ chunk benchmark;
- retrieval load test;
- full-RAG concurrency test;
- worker recovery tests;
- provider failure tests;
- DB/index tuning;
- queue scaling.

**Exit gate**
- documented benchmark results and bottleneck analysis;
- target service-level objectives met or explicitly revised with evidence.

### Phase 14 — Production CI/CD and deployment

**Build**
- staging/prod environments;
- IaC;
- secrets management;
- backups;
- migrations pipeline;
- deploy/rollback;
- synthetic post-deploy RAG checks;
- release versioning.

**Exit gate**
- a fresh environment can be provisioned and deployed from the repository;
- restore/rollback procedure documented and tested.

### Phase 15 — Portfolio polish and release evidence

**Produce**
- public architecture diagram;
- demo seed organization/data;
- evaluation report;
- security report/threat model summary;
- benchmark report;
- screenshots/demo video;
- README quick start;
- API examples;
- design tradeoff document;
- roadmap.

**Exit gate**
- a reviewer can understand and run the product without private explanation.

---

## 41. Required demo scenarios

The final portfolio demo should deliberately show engineering depth.

### Demo 1 — Semantic retrieval

Upload a handbook and ask a paraphrased question whose words do not directly match the source. Show dense/hybrid retrieval.

### Demo 2 — Exact policy code

Ask for `HR-142-B`. Show the lexical branch finding an exact identifier that dense-only search could miss.

### Demo 3 — Reranking

Open retrieval debugger and show fused top-30 candidates becoming a cleaner final top-8 context.

### Demo 4 — Citations

Click `[S2]` and open the exact PDF page/section.

### Demo 5 — Access control

Manager sees a restricted HR document. Normal member asks the exact title and cannot retrieve it.

### Demo 6 — Tenant isolation

Two organizations contain intentionally similar documents. Org A cannot retrieve Org B even with the exact phrase/title.

### Demo 7 — Prompt injection

Upload a controlled test document containing “ignore previous instructions.” The model treats it as evidence text and does not execute it.

### Demo 8 — Version replacement

Replace policy v1 with v2. Search uses v2; v1 remains in history but not active retrieval.

### Demo 9 — Delete propagation

Delete a document and run a verification search proving its chunks are gone from active retrieval.

### Demo 10 — Evaluation

Compare two chunk/retrieval profiles and show metrics before activation.

### Demo 11 — Local-only mode

Set a KB to local-only and demonstrate that external-model call counters remain zero.

### Demo 12 — Failure recovery

Kill an ingestion worker mid-job, restart it, and show idempotent completion without duplicate chunks.

---

## 42. Risk register

| Risk | Impact | Mitigation |
|---|---|---|
| Project scope becomes too large | High | Modular-monolith phases, strict exit gates, no agents until RAG core passes |
| Vector retrieval recall drops under ACL filters | High | iterative HNSW scanning, benchmark filtered retrieval, search-backend abstraction |
| LLM fabricates citations | High | source aliases from backend, identifier validation, regeneration/fail-safe |
| Permission change does not update chunks | Critical | chunk ACL inheritance, sync job, security tests, periodic reconciliation |
| Deleted content remains indexed | Critical | deletion outbox, cascade, orphan sweeper, verification job |
| Prompt injection from documents | High | untrusted-data delimiters, scanner, bounded context, no tool use, red-team tests |
| Cloud provider receives restricted data | Critical | backend-enforced model policy + local-only tests |
| Authentication implementation becomes unsafe | High | OIDC provider, app handles authorization not password cryptography |
| Too many infrastructure components slow development | Medium | Postgres-first modular monolith, optional local profiles, add dedicated systems only after need |
| LLM-as-judge hides regressions | Medium | deterministic retrieval/security metrics + human review |
| Query/answer logs leak sensitive data | High | retention policy, redaction, content logging off/minimized by default |
| Provider model update changes behavior | Medium | pin/version model IDs when possible, evaluation runs record versions, regression checks |
| Embedding model change corrupts search | Critical | no silent fallback; create new index generation/re-embed |
| Web crawler SSRF | Critical | network/domain validation and private-IP blocking |
| Cost runaway | Medium/High | quotas, rate limits, cost ledger, context budgets, alerts |

---

## 43. Self-critique and improvement rounds incorporated into this final plan

### Review round 1 — Architecture/scope

**Problem found:** An “enterprise” plan can easily become a distributed-systems showcase instead of a usable RAG product.

**Changes made:**
- standardized on a modular monolith;
- PostgreSQL handles relational, vector and lexical search first;
- dedicated search infrastructure is hidden behind an interface but not required initially;
- removed premature agents/tool execution.

### Review round 2 — Retrieval correctness

**Problems found:**
- vector-only search misses identifiers;
- fixed top-K retrieval lacks quality controls;
- embedding migrations can make existing vectors incompatible;
- comparison/summary queries need different behavior.

**Changes made:**
- hybrid dense + lexical retrieval;
- RRF fusion;
- cross-encoder reranking;
- typed query router;
- calibrated abstention;
- versioned index generations with side-by-side evaluation/rollback.

### Review round 3 — Security

**Problems found:**
- document-level ACL alone is not sufficient after chunking;
- post-retrieval filtering can expose restricted candidates;
- uploaded/connected documents are an indirect prompt-injection channel;
- source deletion can leave embeddings/search artifacts;
- web ingestion creates SSRF risk;
- cloud providers may violate local/privacy expectations.

**Changes made:**
- copied ACL metadata onto chunks;
- retrieval-time prefiltering;
- tenant RLS;
- prompt-injection/source scanner plus untrusted-data prompting;
- quarantine/malware/file validation;
- delete cascade + orphan verification;
- SSRF controls;
- per-KB model/privacy policy and automated local-only enforcement test.

### Review round 4 — Reliability/operations

**Problems found:**
- enqueue-after-commit can lose ingestion work;
- worker crashes can duplicate or strand jobs;
- profile/prompt changes are hard to reproduce;
- provider failure could produce inconsistent behavior.

**Changes made:**
- transactional outbox;
- idempotent stages + heartbeats/reconciliation;
- immutable RAG-profile/index/prompt versions;
- explicit provider fallback/degraded-mode rules;
- backups/restore and deployment rollback plan.

### Review round 5 — Evaluation/maintainability

**Problems found:**
- “looks good” is not a quality metric;
- LLM-only judging is unreliable;
- a large codebase can hide why answers failed;
- unbounded feature growth can prevent completion.

**Changes made:**
- 200-case categorized golden dataset;
- deterministic retrieval/security metrics plus human review and LLM-assisted metrics;
- retrieval debugger and full query traces;
- strict phase exit gates and non-goals;
- promotion requires quality + security + latency/cost evidence.

No architecture is literally flaw-free, but the remaining risks are now explicit, testable and have defined mitigation/rollback paths instead of being hidden assumptions.

---

## 44. Final definition of done

KnowledgeOS is finished as a business-grade portfolio project when all items below are demonstrably true.

### Product
- [ ] Organization onboarding works.
- [ ] Multiple organizations are isolated.
- [ ] Users/groups/roles work.
- [ ] KB-level and document-level access works.
- [ ] Core document formats ingest.
- [ ] Scanned PDF/image OCR works.
- [ ] Web source and one cloud-document connector work.
- [ ] Version replacement works.
- [ ] Deletion fully propagates.
- [ ] Chat/search UX works.
- [ ] Citations open the exact source location where available.

### RAG
- [ ] Dense retrieval implemented.
- [ ] Lexical retrieval implemented.
- [ ] Hybrid fusion implemented.
- [ ] Reranker implemented.
- [ ] Context budgeting implemented.
- [ ] Evidence-only prompt implemented.
- [ ] Abstention implemented.
- [ ] Citation validation implemented.
- [ ] Conversation rewrite implemented safely.
- [ ] Comparison/summary routing implemented.
- [ ] Index generations support candidate/evaluate/activate/rollback.

### Security
- [ ] OIDC validation.
- [ ] Tenant RLS.
- [ ] Chunk-level authorization metadata.
- [ ] Prompt-injection defenses.
- [ ] File quarantine/malware validation.
- [ ] SSRF protection.
- [ ] XSS/unsafe-Markdown controls.
- [ ] Rate limits.
- [ ] Scoped hashed API keys.
- [ ] Connector secrets encrypted.
- [ ] Local-only model policy enforcement.
- [ ] Threat model documented.
- [ ] Security regression suite passes.

### Evaluation
- [ ] 200+ reviewed cases.
- [ ] Retrieval metrics.
- [ ] Generation/grounding metrics.
- [ ] Citation metrics.
- [ ] Abstention metrics.
- [ ] Authorization/security hard gates.
- [ ] Baseline/candidate comparison.
- [ ] PR smoke eval.
- [ ] full pre-release eval.

### Operations
- [ ] Structured logs.
- [ ] Distributed traces.
- [ ] RAG traces.
- [ ] Cost/token analytics.
- [ ] Queue/job dashboards.
- [ ] Alerts.
- [ ] Backup/restore plan.
- [ ] Idempotent ingestion.
- [ ] Transactional outbox.
- [ ] Load tests.
- [ ] Failure recovery tests.
- [ ] Staging environment.
- [ ] Production/demo environment.
- [ ] CI/CD.
- [ ] Infrastructure as code.

### Portfolio evidence
- [ ] Architecture diagram.
- [ ] ER/data model.
- [ ] threat-model summary.
- [ ] RAG evaluation report.
- [ ] performance benchmark report.
- [ ] demo video.
- [ ] screenshots.
- [ ] README quick start.
- [ ] public API examples.
- [ ] ADRs describing major tradeoffs.
- [ ] clear statement of measured limitations instead of exaggerated “enterprise ready” claims.

---

## 45. Recommended build order in one sentence

**Build the security/tenant boundary first, then reliable ingestion, then permission-aware hybrid search, then reranking/generation/citations, then evaluation and observability, then lifecycle/connectors/local-model policy, and only after those are correct invest in scaling and portfolio polish.**

That order prevents the most expensive architectural rewrites and ensures the finished project demonstrates real production RAG engineering rather than only an attractive chatbot UI.
