"""Ingestion job timeline + reconciler access (S20, T3.6).

- `ingestion_job_events`: one row per state change (state, stage, attempt, safe message) for the
  diagnostics timeline. Tenant table with forced RLS.
- The reconciler (Celery beat, `maintenance.reconcile`) runs as `knowledgeos_dispatcher`, the one
  cross-tenant role (ADR-004 dispatcher exception), extended as narrowly as possible:
  * `ingestion_jobs`: SELECT on the scheduling columns only (no error text, no checkpoints);
  * `uploads`: SELECT on id/org/status/expiry/key and UPDATE of `status` only, to expire
    abandoned uploads;
  * `outbox_events`: INSERT, to re-queue stranded jobs and emit reminders (its existing policy
    already allows all outbox rows).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

from app.db.migration_helpers import DISPATCHER_ROLE, disable_tenant_rls, enable_tenant_rls, grant

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STATES = (
    "RECEIVED", "VALIDATING", "MALWARE_SCAN", "PARSING", "NORMALIZING", "SECURITY_SCAN",
    "CHUNKING", "EMBEDDING", "INDEXING", "VERIFYING", "READY", "PENDING_APPROVAL",
    "QUARANTINED", "FAILED_RETRYABLE", "FAILED_PERMANENT", "CANCELLED",
)  # fmt: skip
_STATES_SQL = ", ".join(f"'{s}'" for s in _STATES)


def _if_dispatcher(statement: str) -> str:
    # Fixed SQL built only from literals in this file.
    return (
        "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'knowledgeos_dispatcher') "  # noqa: S608
        f"THEN {statement}; END IF; END $$;"
    )


_DISPATCHER_SQL = [
    "GRANT SELECT (id, organization_id, state, lease_owner, lease_expires_at, created_at, "
    "updated_at) ON ingestion_jobs TO knowledgeos_dispatcher",
    "CREATE POLICY dispatcher_reconcile ON ingestion_jobs FOR SELECT TO knowledgeos_dispatcher "
    "USING (true)",
    "GRANT SELECT (id, organization_id, status, expires_at, object_key), UPDATE (status) "
    "ON uploads TO knowledgeos_dispatcher",
    "CREATE POLICY dispatcher_expire_uploads ON uploads TO knowledgeos_dispatcher "
    "USING (true) WITH CHECK (true)",
    "GRANT INSERT ON outbox_events TO knowledgeos_dispatcher",
]


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE ingestion_job_events (
          id uuid PRIMARY KEY,
          organization_id uuid NOT NULL REFERENCES organizations (id) ON DELETE CASCADE,
          job_id uuid NOT NULL,
          state varchar(32) NOT NULL CHECK (state IN ({_STATES_SQL})),
          stage varchar(32),
          attempt integer NOT NULL DEFAULT 0,
          message_safe text,
          created_at timestamptz NOT NULL DEFAULT now(),
          FOREIGN KEY (job_id, organization_id)
            REFERENCES ingestion_jobs (id, organization_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_ingestion_job_events_job ON ingestion_job_events (job_id, created_at)"
    )
    enable_tenant_rls("ingestion_job_events")
    grant("SELECT, INSERT", "ingestion_job_events")
    for statement in _DISPATCHER_SQL:
        op.execute(_if_dispatcher(statement))


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS dispatcher_expire_uploads ON uploads")
    op.execute("DROP POLICY IF EXISTS dispatcher_reconcile ON ingestion_jobs")
    op.execute(_if_dispatcher("REVOKE INSERT ON outbox_events FROM knowledgeos_dispatcher"))
    op.execute(_if_dispatcher("REVOKE ALL ON uploads FROM knowledgeos_dispatcher"))
    op.execute(_if_dispatcher("REVOKE ALL ON ingestion_jobs FROM knowledgeos_dispatcher"))
    disable_tenant_rls("ingestion_job_events")
    op.execute("DROP TABLE ingestion_job_events")


assert DISPATCHER_ROLE == "knowledgeos_dispatcher"  # noqa: S101 (literal used above)
