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
