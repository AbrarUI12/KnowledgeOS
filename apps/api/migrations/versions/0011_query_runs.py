"""Query runs and retrieval hits (S25-S26, T4.6; plan §7.8).

- `query_runs`: one row per search (and, from T5.3, per question): who asked, which KBs and
  index generations were searched, the normalized query's **hash** (and its text only when
  retention allows, `RETAIN_QUERY_TEXT`), language, filters, a principal summary that names no
  documents, degraded branches and latencies. Columns for profile/models/rerank/generation are
  filled by later sessions.
- `retrieval_hits`: per-chunk branch ranks and scores, fused score, final rank and whether the hit
  reached the context, for the retrieval debugger. No FK to `chunks`: reindexing deletes chunks,
  but a run's history stays.

Both are tenant tables with forced RLS (D-014).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-15
"""

from collections.abc import Sequence

from alembic import op

from app.db.migration_helpers import disable_tenant_rls, enable_tenant_rls, grant

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DDL = [
    """
    CREATE TABLE query_runs (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      user_id uuid REFERENCES users (id) ON DELETE SET NULL,
      knowledge_base_ids uuid[] NOT NULL CHECK (cardinality(knowledge_base_ids) >= 1),
      query_type varchar(16) NOT NULL CHECK (query_type IN ('search', 'ask')),
      status varchar(16) NOT NULL DEFAULT 'completed'
        CHECK (status IN ('running', 'completed', 'failed', 'abstained')),
      query_hash char(64) NOT NULL CHECK (query_hash ~ '^[0-9a-f]{64}$'),
      query_text text,
      query_language varchar(16),
      filters_json jsonb NOT NULL DEFAULT '{}'::jsonb,
      principal_summary text NOT NULL DEFAULT '',
      index_generations_json jsonb NOT NULL DEFAULT '{}'::jsonb,
      embedding_model text,
      rag_profile_version text,
      reranker_model text,
      generation_model text,
      conversation_id uuid,
      trace_id text,
      degraded text[] NOT NULL DEFAULT '{}',
      retrieval_latency_ms double precision,
      rerank_latency_ms double precision,
      generation_latency_ms double precision,
      total_latency_ms double precision,
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_query_runs_id_organization_id UNIQUE (id, organization_id)
    )
    """,
    "CREATE INDEX ix_query_runs_org_created ON query_runs (organization_id, created_at DESC)",
    "CREATE INDEX ix_query_runs_user ON query_runs (user_id, created_at DESC)",
    """
    CREATE TABLE retrieval_hits (
      query_run_id uuid NOT NULL,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      chunk_id uuid NOT NULL,
      document_id uuid NOT NULL,
      knowledge_base_id uuid NOT NULL,
      rank integer CHECK (rank >= 1),
      dense_rank integer,
      dense_score double precision,
      lexical_rank integer,
      lexical_score double precision,
      fusion_score double precision,
      rerank_score double precision,
      selected_for_context boolean NOT NULL DEFAULT false,
      PRIMARY KEY (query_run_id, chunk_id),
      FOREIGN KEY (query_run_id, organization_id)
        REFERENCES query_runs (id, organization_id) ON DELETE CASCADE
    )
    """,
]


def upgrade() -> None:
    for statement in _DDL:
        op.execute(statement)
    for table in ("query_runs", "retrieval_hits"):
        enable_tenant_rls(table)
        grant("SELECT, INSERT, UPDATE, DELETE", table)


def downgrade() -> None:
    for table in ("retrieval_hits", "query_runs"):
        disable_tenant_rls(table)
        op.execute(f"DROP TABLE {table}")
