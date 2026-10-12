"""Outbox dispatcher role access (S16, T3.1).

`knowledgeos_dispatcher` publishes outbox events for every organization, so it needs cross-tenant
access, but only to `outbox_events` and only what it uses (read pending rows, mark them published
or schedule a retry). Its own RLS policy lets it see all outbox rows; it has no grants on any
other table. See ADR-004 ("Dispatcher exception").

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

from app.db.migration_helpers import DISPATCHER_ROLE, grant, revoke

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICY = (
    "DO $$ BEGIN IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'knowledgeos_dispatcher') THEN "
    "CREATE POLICY dispatcher_publish ON outbox_events TO knowledgeos_dispatcher "
    "USING (true) WITH CHECK (true); END IF; END $$;"
)


def upgrade() -> None:
    grant("SELECT, UPDATE", "outbox_events", DISPATCHER_ROLE)
    op.execute(_POLICY)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS dispatcher_publish ON outbox_events")
    revoke("SELECT, UPDATE", "outbox_events", DISPATCHER_ROLE)
