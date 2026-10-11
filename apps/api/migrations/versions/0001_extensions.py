"""Enable required PostgreSQL extensions (pgvector, pg_trgm).

Revision ID: 0001
Revises:
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Locally the superuser already created these (infra/docker/postgres/init); on Neon the
    # owner role creates them. IF NOT EXISTS makes this safe in both cases.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    # Extensions are shared infrastructure: never drop them on downgrade (other objects or
    # environments may depend on them, and dropping `vector` would destroy embedding data).
    pass
