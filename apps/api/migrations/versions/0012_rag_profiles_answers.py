"""RAG profiles, model policies, answers and citations (S27-S28, T5.3; plan §7.7, §7.8).

- `rag_profiles`: versioned retrieval/generation settings. **Immutable**: the runtime role may
  only SELECT and INSERT (editing = inserting the next version), so no code path can change a
  version a past query run recorded. System presets have `organization_id IS NULL`, are readable
  by every tenant (`system_read` policy) and are seeded here: `default-hybrid-v1`.
- FK `knowledge_bases.active_rag_profile_version_id` (column since 0005): the KB's profile
  version (NULL = the system default); the service checks it's a system or same-org profile.
- `model_policies`: allowed providers per operation, local-only flag, max external
  classification, generation models (primary + fallbacks) and reranker model; per organization,
  optionally per KB. Basic checks now, full enforcement in Session 53.
- `answers` / `citations`: the generated answer of an `ask` query run (text only when retention
  allows) and its validated `[S#]` citations with metadata from the stored alias map.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-22
"""

import json
from collections.abc import Sequence

from alembic import op

from app.db.migration_helpers import disable_tenant_rls, enable_tenant_rls, grant, revoke

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Snapshot of the S27 preset at the time of this migration (later presets are new versions).
DEFAULT_HYBRID_V1 = {
    "dense_k": 50,
    "lexical_k": 50,
    "rrf_k0": 60,
    "dense_weight": 0.55,
    "lexical_weight": 0.45,
    "max_per_document": 3,
    "rerank_candidates": 30,
    "rerank_timeout_seconds": 5.0,
    "allow_degraded_rerank": True,
    "final_context_k": 8,
    "max_context_tokens": 4500,
    "per_document_cap": 3,
    "query_rewrite": False,
    "query_decomposition": False,
    "abstain_min_rerank_score": 0.0,
    "prompt_version": "grounded_answer/v1",
}
DEFAULT_PROFILE_ID = "01920000-0000-7000-8000-00000000d0f1"  # deterministic system row (D-012)

_DDL = [
    """
    CREATE TABLE rag_profiles (
      id uuid PRIMARY KEY,
      organization_id uuid REFERENCES organizations (id) ON DELETE CASCADE,
      name varchar(64) NOT NULL CHECK (name ~ '^[a-z0-9][a-z0-9-]*$'),
      version integer NOT NULL CHECK (version >= 1),
      config_json jsonb NOT NULL,
      created_by uuid REFERENCES users (id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now()
    )
    """,
    "CREATE UNIQUE INDEX uq_rag_profiles_org_name_version "
    "ON rag_profiles (organization_id, name, version) WHERE organization_id IS NOT NULL",
    "CREATE UNIQUE INDEX uq_rag_profiles_system_name_version "
    "ON rag_profiles (name, version) WHERE organization_id IS NULL",
    # The column exists since 0005; only now is there a table to reference.
    "ALTER TABLE knowledge_bases ADD CONSTRAINT fk_knowledge_bases_active_rag_profile "
    "FOREIGN KEY (active_rag_profile_version_id) REFERENCES rag_profiles (id) ON DELETE SET NULL",
    """
    CREATE TABLE model_policies (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      knowledge_base_id uuid,
      local_only boolean NOT NULL DEFAULT false,
      allowed_providers_json jsonb NOT NULL DEFAULT '{}'::jsonb,
      max_external_classification varchar(16) NOT NULL DEFAULT 'internal'
        CHECK (max_external_classification IN ('public', 'internal', 'confidential', 'restricted')),
      generation_models text[] NOT NULL DEFAULT '{}',
      reranker_model text,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz,
      FOREIGN KEY (knowledge_base_id, organization_id)
        REFERENCES knowledge_bases (id, organization_id) ON DELETE CASCADE
    )
    """,
    "CREATE UNIQUE INDEX uq_model_policies_org ON model_policies (organization_id) "
    "WHERE knowledge_base_id IS NULL",
    "CREATE UNIQUE INDEX uq_model_policies_kb ON model_policies (knowledge_base_id) "
    "WHERE knowledge_base_id IS NOT NULL",
    """
    CREATE TABLE answers (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      query_run_id uuid NOT NULL,
      answer_markdown text,
      abstained boolean NOT NULL DEFAULT false,
      abstain_reason varchar(64),
      evidence_status varchar(32),
      model text,
      input_tokens integer,
      output_tokens integer,
      usage_estimated boolean NOT NULL DEFAULT false,
      estimated_cost_usd numeric(12, 6),
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_answers_query_run UNIQUE (query_run_id),
      CONSTRAINT uq_answers_id_organization_id UNIQUE (id, organization_id),
      FOREIGN KEY (query_run_id, organization_id)
        REFERENCES query_runs (id, organization_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE citations (
      answer_id uuid NOT NULL,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      source_alias varchar(8) NOT NULL CHECK (source_alias ~ '^S[1-9][0-9]*$'),
      chunk_id uuid NOT NULL,
      document_version_id uuid NOT NULL,
      page_start integer,
      page_end integer,
      valid boolean NOT NULL DEFAULT true,
      PRIMARY KEY (answer_id, source_alias),
      FOREIGN KEY (answer_id, organization_id)
        REFERENCES answers (id, organization_id) ON DELETE CASCADE
    )
    """,
]


def upgrade() -> None:
    for statement in _DDL:
        op.execute(statement)
    enable_tenant_rls("rag_profiles")
    # System presets (no organization) are readable by every tenant, never writable by it.
    op.execute(
        "CREATE POLICY system_read ON rag_profiles FOR SELECT USING (organization_id IS NULL)"
    )
    grant("SELECT, INSERT", "rag_profiles")
    # Immutable: default privileges would also grant UPDATE/DELETE; take them back explicitly.
    revoke("UPDATE, DELETE, TRUNCATE", "rag_profiles")
    for table in ("model_policies", "answers", "citations"):
        enable_tenant_rls(table)
        grant("SELECT, INSERT, UPDATE, DELETE", table)

    # Seed the system preset as the owner (FORCE RLS lifted for this transaction only, D-014).
    op.execute("ALTER TABLE rag_profiles NO FORCE ROW LEVEL SECURITY")
    config = json.dumps(DEFAULT_HYBRID_V1).replace("'", "''")
    op.execute(
        "INSERT INTO rag_profiles (id, organization_id, name, version, config_json) "  # noqa: S608
        f"VALUES ('{DEFAULT_PROFILE_ID}', NULL, 'default-hybrid', 1, '{config}'::jsonb)"
    )
    op.execute("ALTER TABLE rag_profiles FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in ("citations", "answers", "model_policies"):
        disable_tenant_rls(table)
        op.execute(f"DROP TABLE {table}")
    op.execute(
        "ALTER TABLE knowledge_bases "
        "DROP CONSTRAINT IF EXISTS fk_knowledge_bases_active_rag_profile"
    )
    op.execute("DROP POLICY IF EXISTS system_read ON rag_profiles")
    disable_tenant_rls("rag_profiles")
    op.execute("DROP TABLE rag_profiles")
