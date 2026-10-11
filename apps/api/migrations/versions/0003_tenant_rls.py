"""Row-level security on every tenant-scoped table (Session 08, T1.2).

Tenant context is transaction-local (`set_config(..., true)`, see app.db.tenant):
  app.organization_id  the organization the request acts in
  app.user_id          the authenticated user (lets "my memberships" work before an org is chosen)

Policies (all tables ENABLE + FORCE, so the owner role is bound too):
  tenant_isolation   every tenant table: organization_id = current org (USING + WITH CHECK)
  memberships        + SELECT own rows (user_id = current user)
  organizations      id = current org (all commands) + SELECT orgs the user is a member of
  roles,             + SELECT system rows (organization_id IS NULL) and rows of the user's orgs;
  role_permissions     writes still need the org context, so system roles are read-only here
  users              global, no RLS: services expose only users who share an org with the caller

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

from app.db.migration_helpers import disable_tenant_rls, enable_tenant_rls

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_TABLES = (
    "memberships",
    "roles",
    "role_permissions",
    "groups",
    "group_memberships",
    "invitations",
    "api_keys",
    "audit_events",
)

# NULLIF: once a pooled connection has set the GUC locally, later transactions read '' instead of
# NULL, and ''::uuid would raise instead of matching nothing.
_CONTEXT_FUNCTIONS = (
    "CREATE FUNCTION kos_current_org_id() RETURNS uuid LANGUAGE sql STABLE PARALLEL SAFE "
    "AS $$ SELECT NULLIF(current_setting('app.organization_id', true), '')::uuid $$",
    "CREATE FUNCTION kos_current_user_id() RETURNS uuid LANGUAGE sql STABLE PARALLEL SAFE "
    "AS $$ SELECT NULLIF(current_setting('app.user_id', true), '')::uuid $$",
)

# Orgs the current user actively belongs to. Evaluated under the memberships policies (no
# recursion: memberships' policies don't reference organizations or roles).
_MY_ORGS = (
    "SELECT m.organization_id FROM memberships m "
    "WHERE m.user_id = kos_current_user_id() AND m.status = 'active'"
)


def upgrade() -> None:
    for statement in _CONTEXT_FUNCTIONS:  # asyncpg runs one statement per execute
        op.execute(statement)

    for table in TENANT_TABLES:
        enable_tenant_rls(table)

    op.execute(
        "CREATE POLICY own_memberships_read ON memberships FOR SELECT "
        "USING (user_id = kos_current_user_id())"
    )

    op.execute("ALTER TABLE organizations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON organizations "
        "USING (id = kos_current_org_id()) WITH CHECK (id = kos_current_org_id())"
    )
    op.execute(
        f"CREATE POLICY member_read ON organizations FOR SELECT USING (id IN ({_MY_ORGS}))"
    )

    for table in ("roles", "role_permissions"):
        op.execute(
            f"CREATE POLICY shared_read ON {table} FOR SELECT "
            f"USING (organization_id IS NULL OR organization_id IN ({_MY_ORGS}))"
        )


def downgrade() -> None:
    for table in ("roles", "role_permissions"):
        op.execute(f"DROP POLICY IF EXISTS shared_read ON {table}")
    op.execute("DROP POLICY IF EXISTS member_read ON organizations")
    op.execute("DROP POLICY IF EXISTS own_memberships_read ON memberships")
    for table in (*TENANT_TABLES, "organizations"):
        disable_tenant_rls(table)
    op.execute("DROP FUNCTION IF EXISTS kos_current_user_id()")
    op.execute("DROP FUNCTION IF EXISTS kos_current_org_id()")
