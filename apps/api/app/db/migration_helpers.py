"""Helpers used by Alembic migrations.

Grants live in migrations (not only in the Docker init script) so every environment — local,
Testcontainers, Neon — ends up with identical privileges. Each grant is skipped if the role does
not exist (e.g. a developer database created without the init scripts).
"""

import re

from alembic import op

APP_ROLE = "knowledgeos_app"
DISPATCHER_ROLE = "knowledgeos_dispatcher"

_IDENTIFIER = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_PRIVILEGES = re.compile(
    r"^(SELECT|INSERT|UPDATE|DELETE|TRUNCATE)(, (SELECT|INSERT|UPDATE|DELETE|TRUNCATE))*$"
)


def _checked(privileges: str, table: str, role: str) -> tuple[str, str, str]:
    """Identifiers can't be bound as SQL parameters, so validate them strictly instead."""
    if not _PRIVILEGES.match(privileges):
        raise ValueError(f"invalid privilege list: {privileges!r}")
    for name in (table, role):
        if not _IDENTIFIER.match(name):
            raise ValueError(f"invalid SQL identifier: {name!r}")
    return privileges, table, role


def _guarded(statement: str, role: str) -> str:
    # Inputs were validated by _checked(): only [a-z0-9_] identifiers and fixed privilege keywords.
    condition = f"EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}')"  # noqa: S608
    return f"DO $$ BEGIN IF {condition} THEN {statement}; END IF; END $$;"


def grant(privileges: str, table: str, role: str = APP_ROLE) -> None:
    privileges, table, role = _checked(privileges, table, role)
    op.execute(_guarded(f"GRANT {privileges} ON TABLE {table} TO {role}", role))


def revoke(privileges: str, table: str, role: str = APP_ROLE) -> None:
    privileges, table, role = _checked(privileges, table, role)
    op.execute(_guarded(f"REVOKE {privileges} ON TABLE {table} FROM {role}", role))


# --------------------------------------------------------------------------- row-level security
# Policy expressions call kos_current_org_id() / kos_current_user_id() (migration 0003). They read
# the transaction-local settings written by app.db.tenant.set_tenant_context and return NULL when
# unset, so a missing tenant context matches no rows (fail closed).

TENANT_PREDICATE = "organization_id = kos_current_org_id()"


def _table(table: str) -> str:
    if not _IDENTIFIER.match(table):
        raise ValueError(f"invalid SQL identifier: {table!r}")
    return table


def enable_tenant_rls(table: str) -> None:
    """Enable + FORCE RLS on a tenant table with the standard isolation policy.

    FORCE makes the policy bind the table owner too; only superusers / BYPASSRLS roles skip it.
    Every new table with an `organization_id` column must call this (tests/test_rls.py checks).
    """
    table = _table(table)
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"USING ({TENANT_PREDICATE}) WITH CHECK ({TENANT_PREDICATE})"
    )


def disable_tenant_rls(table: str) -> None:
    table = _table(table)
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
