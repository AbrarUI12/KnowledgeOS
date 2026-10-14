"""At most one unfinished ingestion job per document version (T3.6 review).

Retry, reindex and cancel serialize on the document row lock; this partial unique index is the
database backstop for the same invariant, so a code path that forgets the lock fails loudly
instead of running two jobs that race on one version's status and chunks. "Unfinished" means not
in a terminal state (`TERMINAL_INGESTION_STATES`: READY, QUARANTINED, FAILED_PERMANENT,
CANCELLED).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX uq_ingestion_jobs_one_active_per_version "
        "ON ingestion_jobs (document_version_id) "
        "WHERE state NOT IN ('READY', 'QUARANTINED', 'FAILED_PERMANENT', 'CANCELLED')"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_ingestion_jobs_one_active_per_version")
