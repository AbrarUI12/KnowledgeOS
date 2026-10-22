"""Query runs can be `cancelled` (S29, T5.4): closing the SSE connection cancels generation and
the run records it (docs/api/sse-events.md).

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE query_runs DROP CONSTRAINT query_runs_status_check")
    op.execute(
        "ALTER TABLE query_runs ADD CONSTRAINT query_runs_status_check "
        "CHECK (status IN ('running', 'completed', 'failed', 'abstained', 'cancelled'))"
    )


def downgrade() -> None:
    op.execute("UPDATE query_runs SET status = 'failed' WHERE status = 'cancelled'")
    op.execute("ALTER TABLE query_runs DROP CONSTRAINT query_runs_status_check")
    op.execute(
        "ALTER TABLE query_runs ADD CONSTRAINT query_runs_status_check "
        "CHECK (status IN ('running', 'completed', 'failed', 'abstained'))"
    )
