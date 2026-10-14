"""Index generations and chunks (S19, T3.5; plan §7.6, ADR-007).

- `index_generations`: one `active` generation per KB (unique partial index), candidates built
  side by side later (ADR-007). Generation #1 is backfilled for existing KBs and created with
  every new KB.
- `chunks`: core columns. `embedding`, `search_vector` and `access_principals` arrive with indexing
  in Session 23. Unique `(document_version_id, index_generation_id, ordinal)` makes the CHUNKING
  stage's delete-then-insert idempotent.
- Composite FKs everywhere (D-012), including `knowledge_bases.active_index_generation_id`, which
  must name a generation of the same KB and organization.

The backfill writes tenant rows as the owner, so it lifts FORCE RLS on the two tables for the
duration of this migration's transaction only (D-014).

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

from app.db.migration_helpers import disable_tenant_rls, enable_tenant_rls, grant

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DDL = [
    """
    CREATE TABLE index_generations (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      knowledge_base_id uuid NOT NULL,
      generation_number integer NOT NULL CHECK (generation_number >= 1),
      status varchar(16) NOT NULL DEFAULT 'building'
        CHECK (status IN ('building', 'candidate', 'active', 'retired', 'failed')),
      embedding_provider text NOT NULL,
      embedding_model text NOT NULL,
      embedding_dimension integer NOT NULL CHECK (embedding_dimension > 0),
      chunker_name text NOT NULL,
      chunker_config_json jsonb NOT NULL DEFAULT '{}'::jsonb,
      parser_pipeline_version text NOT NULL DEFAULT '1',
      retrieval_profile_version_id uuid,
      created_at timestamptz NOT NULL DEFAULT now(),
      activated_at timestamptz,
      retired_at timestamptz,
      CONSTRAINT uq_index_generations_kb_number UNIQUE (knowledge_base_id, generation_number),
      CONSTRAINT uq_index_generations_id_organization_id UNIQUE (id, organization_id),
      CONSTRAINT uq_index_generations_id_org_kb UNIQUE (id, organization_id, knowledge_base_id),
      FOREIGN KEY (knowledge_base_id, organization_id)
        REFERENCES knowledge_bases (id, organization_id) ON DELETE CASCADE
    )
    """,
    "CREATE UNIQUE INDEX uq_index_generations_one_active ON index_generations "
    "(knowledge_base_id) WHERE status = 'active'",
    "ALTER TABLE knowledge_bases ADD CONSTRAINT fk_knowledge_bases_active_index_generation "
    "FOREIGN KEY (active_index_generation_id, organization_id, id) "
    "REFERENCES index_generations (id, organization_id, knowledge_base_id) "
    "ON DELETE SET NULL (active_index_generation_id) DEFERRABLE INITIALLY DEFERRED",
    "ALTER TABLE ingestion_jobs ADD CONSTRAINT fk_ingestion_jobs_index_generation "
    "FOREIGN KEY (index_generation_id, organization_id) "
    "REFERENCES index_generations (id, organization_id) ON DELETE SET NULL (index_generation_id)",
    """
    CREATE TABLE chunks (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      knowledge_base_id uuid NOT NULL,
      document_id uuid NOT NULL,
      document_version_id uuid NOT NULL,
      index_generation_id uuid NOT NULL,
      ordinal integer NOT NULL CHECK (ordinal >= 0),
      parent_chunk_id uuid,
      is_parent boolean NOT NULL DEFAULT false,
      block_type varchar(16) NOT NULL,
      section_path text[] NOT NULL DEFAULT '{}',
      block_ids text[] NOT NULL DEFAULT '{}',
      content text NOT NULL,
      embedding_text text NOT NULL,
      content_hash char(64) NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
      token_count integer NOT NULL CHECK (token_count >= 0),
      page_start integer,
      page_end integer,
      location_json jsonb NOT NULL DEFAULT '{}'::jsonb,
      metadata_json jsonb NOT NULL DEFAULT '{}'::jsonb,
      visibility varchar(16) NOT NULL DEFAULT 'visible'
        CHECK (visibility IN ('visible', 'hidden')),
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_chunks_version_generation_ordinal
        UNIQUE (document_version_id, index_generation_id, ordinal),
      CONSTRAINT uq_chunks_id_organization_id UNIQUE (id, organization_id),
      FOREIGN KEY (document_version_id, organization_id)
        REFERENCES document_versions (id, organization_id) ON DELETE CASCADE,
      FOREIGN KEY (document_id, organization_id)
        REFERENCES documents (id, organization_id) ON DELETE CASCADE,
      FOREIGN KEY (index_generation_id, organization_id)
        REFERENCES index_generations (id, organization_id) ON DELETE CASCADE,
      FOREIGN KEY (knowledge_base_id, organization_id)
        REFERENCES knowledge_bases (id, organization_id) ON DELETE CASCADE,
      FOREIGN KEY (parent_chunk_id, organization_id)
        REFERENCES chunks (id, organization_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_chunks_generation_document ON chunks (index_generation_id, document_id)",
    "CREATE INDEX ix_chunks_content_hash ON chunks (organization_id, content_hash)",
]

# Snapshot of the embedding/chunker defaults at the time of this migration (D-004).
_BACKFILL = """
INSERT INTO index_generations (
  id, organization_id, knowledge_base_id, generation_number, status, embedding_provider,
  embedding_model, embedding_dimension, chunker_name, chunker_config_json, activated_at
)
SELECT gen_random_uuid(), kb.organization_id, kb.id, 1, 'active', 'sentence_transformers',
       'Qwen/Qwen3-Embedding-0.6B', 1024, 'structure_aware', '{"version": "1"}'::jsonb, now()
FROM knowledge_bases kb
WHERE NOT EXISTS (SELECT 1 FROM index_generations g WHERE g.knowledge_base_id = kb.id)
"""

_ACTIVATE = """
UPDATE knowledge_bases kb SET active_index_generation_id = g.id
FROM index_generations g
WHERE g.knowledge_base_id = kb.id AND g.status = 'active' AND kb.active_index_generation_id IS NULL
"""


def upgrade() -> None:
    for statement in _DDL:
        op.execute(statement)
    for table in ("index_generations", "chunks"):
        enable_tenant_rls(table)
        grant("SELECT, INSERT, UPDATE, DELETE", table)

    # Owner-side backfill across organizations (see module docstring).
    op.execute("ALTER TABLE index_generations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE knowledge_bases NO FORCE ROW LEVEL SECURITY")
    op.execute(_BACKFILL)
    op.execute(_ACTIVATE)
    op.execute("ALTER TABLE knowledge_bases FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE index_generations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE ingestion_jobs DROP CONSTRAINT fk_ingestion_jobs_index_generation")
    op.execute(
        "ALTER TABLE knowledge_bases DROP CONSTRAINT fk_knowledge_bases_active_index_generation"
    )
    for table in ("chunks", "index_generations"):
        disable_tenant_rls(table)
        op.execute(f"DROP TABLE {table}")
