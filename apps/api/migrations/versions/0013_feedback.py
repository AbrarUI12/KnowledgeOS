"""Answer and search feedback (S31, T5.4; plan §7.9).

One row per person per query run (`up`/`down`, an optional reason code and comment); giving
feedback again replaces it. Tenant table with forced RLS (D-014).

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

from app.db.migration_helpers import disable_tenant_rls, enable_tenant_rls, grant

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feedback (
          id uuid PRIMARY KEY,
          organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
          query_run_id uuid NOT NULL,
          user_id uuid NOT NULL REFERENCES users (id) ON DELETE CASCADE,
          rating varchar(8) NOT NULL CHECK (rating IN ('up', 'down')),
          reason_code varchar(64),
          comment text,
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz,
          CONSTRAINT uq_feedback_run_user UNIQUE (query_run_id, user_id),
          FOREIGN KEY (query_run_id, organization_id)
            REFERENCES query_runs (id, organization_id) ON DELETE CASCADE
        )
        """
    )
    enable_tenant_rls("feedback")
    grant("SELECT, INSERT, UPDATE, DELETE", "feedback")


def downgrade() -> None:
    disable_tenant_rls("feedback")
    op.execute("DROP TABLE feedback")
