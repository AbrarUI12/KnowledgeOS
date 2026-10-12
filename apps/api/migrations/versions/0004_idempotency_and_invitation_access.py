"""Idempotency keys + invitation lookup by token (Session 09, T1.3).

- `idempotency_keys`: per-user stored responses for `Idempotency-Key` (forced RLS, own rows only).
- invitations: SELECT policy matching a transaction-local `app.invitation_token_hash`, so the
  accept endpoint can find an invitation before the caller is a member. Knowing the token is
  the capability; only its hash is stored and compared.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.migration_helpers import grant

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=200), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_idempotency_keys_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("user_id", "key", name=op.f("uq_idempotency_keys_user_id")),
    )
    op.execute("ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE idempotency_keys FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY own_keys ON idempotency_keys "
        "USING (user_id = kos_current_user_id()) WITH CHECK (user_id = kos_current_user_id())"
    )
    grant("SELECT, INSERT, UPDATE, DELETE", "idempotency_keys")

    op.execute(
        "CREATE POLICY token_holder_read ON invitations FOR SELECT "
        "USING (token_hash = NULLIF(current_setting('app.invitation_token_hash', true), ''))"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS token_holder_read ON invitations")
    op.drop_table("idempotency_keys")
