"""Knowledge bases, sources, documents, versions, ACLs, uploads, ingestion jobs, outbox (S12, T2.1).

Every table carries `organization_id` with forced RLS (tests/test_rls.py meta-test). Child rows
reference their parent through composite `(id, organization_id)` foreign keys, so a row can never
point into another tenant (D-012). Plan §7.3-§7.5.

`knowledge_bases.active_index_generation_id` / `active_rag_profile_version_id` are nullable
columns whose foreign keys arrive with their tables (Sessions 19 and 27).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

from app.db.migration_helpers import disable_tenant_rls, enable_tenant_rls, grant

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Literal snapshot of app.domain.enums.IngestionState at the time of this migration.
_INGESTION_STATES = (
    "RECEIVED", "VALIDATING", "MALWARE_SCAN", "PARSING", "NORMALIZING", "SECURITY_SCAN",
    "CHUNKING", "EMBEDDING", "INDEXING", "VERIFYING", "READY", "PENDING_APPROVAL",
    "QUARANTINED", "FAILED_RETRYABLE", "FAILED_PERMANENT", "CANCELLED",
)  # fmt: skip
_STATES_SQL = ", ".join(f"'{s}'" for s in _INGESTION_STATES)

TABLES = (
    "knowledge_bases",
    "knowledge_base_acl",
    "data_sources",
    "documents",
    "document_versions",
    "source_objects",
    "document_acl",
    "uploads",
    "ingestion_jobs",
    "outbox_events",
)

_ACL_COLUMNS = """
  organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
  principal_type varchar(16) NOT NULL CHECK (principal_type IN ('user', 'group', 'role')),
  principal_id text NOT NULL,
  permission varchar(16) NOT NULL CHECK (permission IN ('query', 'manage')),
  created_at timestamptz NOT NULL DEFAULT now()
"""

_DDL = [
    """
    CREATE TABLE knowledge_bases (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      name text NOT NULL,
      slug varchar(63) NOT NULL CHECK (slug ~ '^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$'),
      description text,
      visibility varchar(16) NOT NULL DEFAULT 'organization'
        CHECK (visibility IN ('organization', 'restricted')),
      active_index_generation_id uuid,
      active_rag_profile_version_id uuid,
      model_policy_id uuid,
      retention_policy_id uuid,
      acl_propagated_at timestamptz,
      created_by uuid REFERENCES users (id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz,
      archived_at timestamptz,
      CONSTRAINT uq_knowledge_bases_organization_id_slug UNIQUE (organization_id, slug),
      CONSTRAINT uq_knowledge_bases_id_organization_id UNIQUE (id, organization_id)
    )
    """,
    f"""
    CREATE TABLE knowledge_base_acl (
      knowledge_base_id uuid NOT NULL,
      {_ACL_COLUMNS},
      PRIMARY KEY (knowledge_base_id, principal_type, principal_id, permission),
      FOREIGN KEY (knowledge_base_id, organization_id)
        REFERENCES knowledge_bases (id, organization_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE data_sources (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      knowledge_base_id uuid NOT NULL,
      type varchar(32) NOT NULL,
      name text NOT NULL,
      status varchar(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'paused', 'disabled')),
      trust_level varchar(16) NOT NULL DEFAULT 'internal',
      permission_sync_mode varchar(16) NOT NULL DEFAULT 'none',
      encrypted_config_ref text,
      sync_cursor text,
      last_sync_at timestamptz,
      last_sync_status varchar(32),
      created_by uuid REFERENCES users (id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_data_sources_id_organization_id UNIQUE (id, organization_id),
      FOREIGN KEY (knowledge_base_id, organization_id)
        REFERENCES knowledge_bases (id, organization_id) ON DELETE CASCADE
    )
    """,
    # Exactly one built-in upload source per knowledge base.
    "CREATE UNIQUE INDEX uq_data_sources_kb_upload ON data_sources (knowledge_base_id) "
    "WHERE type = 'upload'",
    """
    CREATE TABLE documents (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      knowledge_base_id uuid NOT NULL,
      source_id uuid NOT NULL,
      canonical_key text,
      title text NOT NULL,
      document_type varchar(64),
      classification varchar(16) NOT NULL DEFAULT 'internal'
        CHECK (classification IN ('public', 'internal', 'confidential', 'restricted')),
      status varchar(16) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'archived', 'deleted')),
      active_version_id uuid,
      created_by uuid REFERENCES users (id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz,
      archived_at timestamptz,
      CONSTRAINT uq_documents_id_organization_id UNIQUE (id, organization_id),
      FOREIGN KEY (knowledge_base_id, organization_id)
        REFERENCES knowledge_bases (id, organization_id) ON DELETE CASCADE,
      FOREIGN KEY (source_id, organization_id)
        REFERENCES data_sources (id, organization_id) ON DELETE RESTRICT
    )
    """,
    "CREATE INDEX ix_documents_kb ON documents (knowledge_base_id, created_at DESC)",
    "CREATE UNIQUE INDEX uq_documents_kb_canonical_key ON documents (knowledge_base_id, "
    "canonical_key) WHERE canonical_key IS NOT NULL",
    f"""
    CREATE TABLE document_versions (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      document_id uuid NOT NULL,
      version_number integer NOT NULL CHECK (version_number >= 1),
      sha256 char(64) CHECK (sha256 ~ '^[0-9a-f]{{64}}$'),
      object_key text,
      canonical_artifact_key text,
      mime_type text,
      size_bytes bigint CHECK (size_bytes >= 0),
      source_modified_at timestamptz,
      effective_from timestamptz,
      effective_to timestamptz,
      parser_name text,
      parser_version text,
      integrity_status varchar(16) NOT NULL DEFAULT 'pending'
        CHECK (integrity_status IN ('pending', 'verified', 'mismatch', 'failed')),
      approval_status varchar(16) NOT NULL DEFAULT 'not_required'
        CHECK (approval_status IN ('not_required', 'pending', 'approved', 'rejected')),
      ingestion_status varchar(32) NOT NULL DEFAULT 'RECEIVED'
        CHECK (ingestion_status IN ({_STATES_SQL})),
      created_by uuid REFERENCES users (id) ON DELETE SET NULL,
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_document_versions_document_id_version_number
        UNIQUE (document_id, version_number),
      CONSTRAINT uq_document_versions_id_organization_id UNIQUE (id, organization_id),
      CONSTRAINT uq_document_versions_id_organization_id_document_id
        UNIQUE (id, organization_id, document_id),
      FOREIGN KEY (document_id, organization_id)
        REFERENCES documents (id, organization_id) ON DELETE CASCADE
    )
    """,
    # The active version must belong to this document and this organization (D-012). MATCH SIMPLE:
    # a NULL active_version_id skips the check; deleting the version clears only that column.
    "ALTER TABLE documents ADD CONSTRAINT fk_documents_active_version_id_document_versions "
    "FOREIGN KEY (active_version_id, organization_id, id) "
    "REFERENCES document_versions (id, organization_id, document_id) "
    "ON DELETE SET NULL (active_version_id) DEFERRABLE INITIALLY DEFERRED",
    """
    CREATE TABLE source_objects (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      source_id uuid NOT NULL,
      external_id text NOT NULL,
      external_revision text,
      document_id uuid,
      source_url text,
      source_modified_at timestamptz,
      deleted_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_source_objects_source_id_external_id UNIQUE (source_id, external_id),
      FOREIGN KEY (source_id, organization_id)
        REFERENCES data_sources (id, organization_id) ON DELETE CASCADE,
      FOREIGN KEY (document_id, organization_id)
        REFERENCES documents (id, organization_id) ON DELETE CASCADE
    )
    """,
    f"""
    CREATE TABLE document_acl (
      document_id uuid NOT NULL,
      {_ACL_COLUMNS},
      PRIMARY KEY (document_id, principal_type, principal_id, permission),
      FOREIGN KEY (document_id, organization_id)
        REFERENCES documents (id, organization_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE uploads (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      knowledge_base_id uuid NOT NULL,
      document_id uuid,
      document_version_id uuid,
      created_by uuid REFERENCES users (id) ON DELETE SET NULL,
      filename text NOT NULL,
      declared_mime text NOT NULL,
      declared_size bigint NOT NULL CHECK (declared_size > 0),
      object_key text NOT NULL,
      status varchar(16) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed', 'expired', 'failed')),
      expires_at timestamptz NOT NULL,
      completed_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      CONSTRAINT uq_uploads_object_key UNIQUE (object_key),
      FOREIGN KEY (knowledge_base_id, organization_id)
        REFERENCES knowledge_bases (id, organization_id) ON DELETE CASCADE,
      FOREIGN KEY (document_id, organization_id)
        REFERENCES documents (id, organization_id) ON DELETE CASCADE,
      FOREIGN KEY (document_version_id, organization_id)
        REFERENCES document_versions (id, organization_id) ON DELETE SET NULL (document_version_id)
    )
    """,
    f"""
    CREATE TABLE ingestion_jobs (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      document_version_id uuid NOT NULL,
      index_generation_id uuid,
      state varchar(32) NOT NULL DEFAULT 'RECEIVED' CHECK (state IN ({_STATES_SQL})),
      stage varchar(32),
      progress_percent smallint NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
      attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
      error_code varchar(64),
      error_detail_safe text,
      stage_checkpoints jsonb NOT NULL DEFAULT '{{}}'::jsonb,
      lease_owner text,
      lease_expires_at timestamptz,
      started_at timestamptz,
      completed_at timestamptz,
      heartbeat_at timestamptz,
      created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz,
      CONSTRAINT uq_ingestion_jobs_id_organization_id UNIQUE (id, organization_id),
      FOREIGN KEY (document_version_id, organization_id)
        REFERENCES document_versions (id, organization_id) ON DELETE CASCADE
    )
    """,
    "CREATE INDEX ix_ingestion_jobs_version ON ingestion_jobs (document_version_id)",
    "CREATE INDEX ix_ingestion_jobs_org_state ON ingestion_jobs (organization_id, state)",
    """
    CREATE TABLE outbox_events (
      id uuid PRIMARY KEY,
      organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
      event_type varchar(64) NOT NULL,
      aggregate_type varchar(64) NOT NULL,
      aggregate_id text NOT NULL,
      payload_json jsonb NOT NULL DEFAULT '{}'::jsonb,
      created_at timestamptz NOT NULL DEFAULT now(),
      available_at timestamptz NOT NULL DEFAULT now(),
      published_at timestamptz,
      attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
      last_error text
    )
    """,
    "CREATE INDEX ix_outbox_events_pending ON outbox_events (available_at) "
    "WHERE published_at IS NULL",
]


def upgrade() -> None:
    for statement in _DDL:  # asyncpg executes one statement per call
        op.execute(statement)
    for table in TABLES:
        enable_tenant_rls(table)
        grant("SELECT, INSERT, UPDATE, DELETE", table)


def downgrade() -> None:
    for table in TABLES:
        disable_tenant_rls(table)
    op.execute(
        "ALTER TABLE documents DROP CONSTRAINT fk_documents_active_version_id_document_versions"
    )
    for table in reversed(TABLES):
        op.execute(f"DROP TABLE {table}")
