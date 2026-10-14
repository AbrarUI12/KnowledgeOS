"""Chunk indexing: vectors, full text, identifiers and materialized ACLs (S22-S23, T4.2).

- `embedding vector(1024)`: child chunks only (parents are context, never retrieved directly);
  HNSW with cosine distance (m = 16, ef_construction = 64).
- `embedding_text_hash`: sha256 of `embedding_text`, for reusing vectors inside the organization
  (plan §13.1) without comparing the texts themselves.
- `search_vector` (title A, section path B, body C) built with the chunk's own `fts_config`
  (detected language, `simple` fallback), so a query must use the same configuration per row.
- `identifiers`: exact codes such as `HR-142-B` from the chunker, for lexical boosting.
- `access_principals`: the ACL tokens (`org:`, `user:`, `group:`, `role:`) materialized from the KB
  and document ACLs, matched against the caller's tokens at query time (ADR-004 layer 3).
  Group membership and role changes need no rewrite: the tokens name the group or role.
- B-tree indexes for the join-based retrieval predicate, plus a trigram index on document titles.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = [
    "ALTER TABLE chunks ADD COLUMN embedding_text_hash char(64) "
    "CHECK (embedding_text_hash ~ '^[0-9a-f]{64}$')",
    "ALTER TABLE chunks ADD COLUMN embedding vector(1024)",
    "ALTER TABLE chunks ADD COLUMN search_vector tsvector",
    "ALTER TABLE chunks ADD COLUMN fts_config regconfig",
    "ALTER TABLE chunks ADD COLUMN identifiers text[] NOT NULL DEFAULT '{}'",
    "ALTER TABLE chunks ADD COLUMN access_principals text[] NOT NULL DEFAULT '{}'",
    # Parents are context for their children; only children carry vectors.
    "ALTER TABLE chunks ADD CONSTRAINT ck_chunks_parent_without_embedding "
    "CHECK (NOT is_parent OR embedding IS NULL)",
]

_INDEXES = {
    "ix_chunks_embedding_hnsw": "chunks USING hnsw (embedding vector_cosine_ops) "
    "WITH (m = 16, ef_construction = 64)",
    "ix_chunks_search_vector": "chunks USING gin (search_vector)",
    "ix_chunks_access_principals": "chunks USING gin (access_principals)",
    "ix_chunks_identifiers": "chunks USING gin (identifiers)",
    "ix_chunks_org_kb_generation": "chunks (organization_id, knowledge_base_id, "
    "index_generation_id)",
    "ix_chunks_document_version": "chunks (document_version_id)",
    "ix_chunks_embedding_reuse": "chunks (organization_id, embedding_text_hash) "
    "WHERE embedding IS NOT NULL",
    "ix_documents_title_trgm": "documents USING gin (title gin_trgm_ops)",
}


def upgrade() -> None:
    for statement in _COLUMNS:
        op.execute(statement)
    for name, definition in _INDEXES.items():
        op.execute(f"CREATE INDEX {name} ON {definition}")


def downgrade() -> None:
    for name in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
    op.execute("ALTER TABLE chunks DROP CONSTRAINT IF EXISTS ck_chunks_parent_without_embedding")
    for column in (
        "access_principals",
        "identifiers",
        "fts_config",
        "search_vector",
        "embedding",
        "embedding_text_hash",
    ):
        op.execute(f"ALTER TABLE chunks DROP COLUMN IF EXISTS {column}")
