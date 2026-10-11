"""Integration tests for the identity/organization schema (migration 0002) on real PostgreSQL."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import asyncpg
import pytest

from app.auth.permissions import SYSTEM_ROLE_PERMISSIONS, SystemRole, system_role_id
from app.core.config import Settings

pytestmark = pytest.mark.integration


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def admin(admin_dsn: str, migrated_settings: Settings) -> AsyncIterator[asyncpg.Connection]:
    """Superuser connection for setup/cleanup across organizations (forced RLS binds the admin)."""
    conn = await asyncpg.connect(admin_dsn)
    try:
        yield conn
    finally:
        # Clean up everything except the seeded system roles.
        async with conn.transaction():
            await conn.execute("SET LOCAL app.audit_purge = 'on'")
            await conn.execute("DELETE FROM audit_events")
            await conn.execute("DELETE FROM organizations")
            await conn.execute("DELETE FROM users")
        await conn.close()


@pytest.fixture
async def app_conn(
    migrated_settings: Settings, admin: asyncpg.Connection
) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(_dsn(migrated_settings.database_url.get_secret_value()))
    try:
        yield conn
    finally:
        await conn.close()


async def make_org(conn: asyncpg.Connection, slug: str | None = None) -> uuid.UUID:
    slug = slug or f"org-{uuid.uuid4().hex[:8]}"
    return await conn.fetchval(  # type: ignore[no-any-return]
        "INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3) RETURNING id",
        uuid.uuid4(),
        slug.title(),
        slug,
    )


async def make_user(conn: asyncpg.Connection, sub: str | None = None) -> uuid.UUID:
    return await conn.fetchval(  # type: ignore[no-any-return]
        "INSERT INTO users (id, issuer, external_subject, email) "
        "VALUES ($1, $2, $3, $4) RETURNING id",
        uuid.uuid4(),
        "http://issuer.test",
        sub or uuid.uuid4().hex,
        "someone@example.test",
    )


async def make_custom_role(conn: asyncpg.Connection, org_id: uuid.UUID, key: str) -> uuid.UUID:
    return await conn.fetchval(  # type: ignore[no-any-return]
        "INSERT INTO roles (id, organization_id, key, name) VALUES ($1, $2, $3, $4) RETURNING id",
        uuid.uuid4(),
        org_id,
        key,
        key.title(),
    )


# --------------------------------------------------------------------------- seed / drift


async def test_system_roles_match_permission_catalogue(admin: asyncpg.Connection) -> None:
    rows = await admin.fetch(
        """
        SELECT r.id, r.key, r.is_system, array_agg(rp.permission ORDER BY rp.permission) AS perms
        FROM roles r JOIN role_permissions rp ON rp.role_id = r.id
        WHERE r.organization_id IS NULL
        GROUP BY r.id, r.key, r.is_system
        """
    )
    stored: dict[str, Any] = {r["key"]: r for r in rows}

    assert set(stored) == {role.value for role in SystemRole}
    for role, perms in SYSTEM_ROLE_PERMISSIONS.items():
        row = stored[role.value]
        assert row["is_system"] is True
        assert row["id"] == system_role_id(role), "migration and app disagree on role IDs"
        assert set(row["perms"]) == {p.value for p in perms}, f"drift for role {role}"


# --------------------------------------------------------------------------- constraints


async def test_user_identity_is_unique_per_issuer(admin: asyncpg.Connection) -> None:
    await make_user(admin, sub="abc")
    with pytest.raises(asyncpg.UniqueViolationError):
        await make_user(admin, sub="abc")


async def test_org_slug_is_unique_and_well_formed(admin: asyncpg.Connection) -> None:
    await make_org(admin, "acme")
    with pytest.raises(asyncpg.UniqueViolationError):
        await make_org(admin, "acme")
    with pytest.raises(asyncpg.CheckViolationError):
        await make_org(admin, "Not A Slug!")


async def test_membership_is_unique_per_org_and_user(admin: asyncpg.Connection) -> None:
    org, user = await make_org(admin), await make_user(admin)
    member = system_role_id(SystemRole.MEMBER)
    sql = "INSERT INTO memberships (id, organization_id, user_id, role_id) VALUES ($1, $2, $3, $4)"
    await admin.execute(sql, uuid.uuid4(), org, user, member)
    with pytest.raises(asyncpg.UniqueViolationError):
        await admin.execute(sql, uuid.uuid4(), org, user, member)


async def test_group_names_unique_within_an_org_only(admin: asyncpg.Connection) -> None:
    org_a, org_b = await make_org(admin), await make_org(admin)
    sql = "INSERT INTO groups (id, organization_id, name) VALUES ($1, $2, $3)"
    await admin.execute(sql, uuid.uuid4(), org_a, "HR")
    await admin.execute(sql, uuid.uuid4(), org_b, "HR")  # same name in another org is fine
    with pytest.raises(asyncpg.UniqueViolationError):
        await admin.execute(sql, uuid.uuid4(), org_a, "HR")


async def test_system_role_keys_are_unique_despite_null_org(admin: asyncpg.Connection) -> None:
    with pytest.raises(asyncpg.UniqueViolationError):
        await admin.execute(
            "INSERT INTO roles (id, organization_id, key, name, is_system) "
            "VALUES ($1, NULL, 'owner', 'Duplicate', true)",
            uuid.uuid4(),
        )


async def test_custom_roles_cannot_claim_to_be_system(admin: asyncpg.Connection) -> None:
    org = await make_org(admin)
    with pytest.raises(asyncpg.CheckViolationError):
        await admin.execute(
            "INSERT INTO roles (id, organization_id, key, name, is_system) "
            "VALUES ($1, $2, 'sneaky', 'Sneaky', true)",
            uuid.uuid4(),
            org,
        )


# --------------------------------------------------------------------------- cross-tenant integrity


async def test_group_membership_cannot_point_to_another_orgs_group(
    admin: asyncpg.Connection,
) -> None:
    org_a, org_b, user = await make_org(admin), await make_org(admin), await make_user(admin)
    group_in_a = await admin.fetchval(
        "INSERT INTO groups (id, organization_id, name) VALUES ($1, $2, 'HR') RETURNING id",
        uuid.uuid4(),
        org_a,
    )
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        await admin.execute(
            "INSERT INTO group_memberships (group_id, user_id, organization_id) "
            "VALUES ($1, $2, $3)",
            group_in_a,
            user,
            org_b,
        )


async def test_membership_role_must_be_system_or_same_org(admin: asyncpg.Connection) -> None:
    org_a, org_b, user = await make_org(admin), await make_org(admin), await make_user(admin)
    custom_in_a = await make_custom_role(admin, org_a, "auditor")
    sql = "INSERT INTO memberships (id, organization_id, user_id, role_id) VALUES ($1, $2, $3, $4)"

    with pytest.raises(asyncpg.ForeignKeyViolationError, match="another organization"):
        await admin.execute(sql, uuid.uuid4(), org_b, user, custom_in_a)

    await admin.execute(sql, uuid.uuid4(), org_a, user, custom_in_a)  # same org: allowed
    await admin.execute(sql, uuid.uuid4(), org_b, user, system_role_id(SystemRole.VIEWER))


# --------------------------------------------------------------------------- audit append-only


async def _insert_audit(conn: asyncpg.Connection, org: uuid.UUID) -> uuid.UUID:
    return await conn.fetchval(  # type: ignore[no-any-return]
        "INSERT INTO audit_events (id, organization_id, actor_type, action, resource_type) "
        "VALUES ($1, $2, 'system', 'org.created', 'organization') RETURNING id",
        uuid.uuid4(),
        org,
    )


async def test_app_role_can_insert_but_never_modify_audit_events(
    admin: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    org = await make_org(admin)
    async with app_conn.transaction():
        await app_conn.execute("SELECT set_config('app.organization_id', $1, true)", str(org))
        event = await _insert_audit(app_conn, org)

    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("UPDATE audit_events SET action = 'tampered' WHERE id = $1", event)
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("DELETE FROM audit_events WHERE id = $1", event)


async def test_audit_trigger_blocks_even_a_superuser(admin: asyncpg.Connection) -> None:
    org = await make_org(admin)
    event = await _insert_audit(admin, org)

    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="append-only"):
        await admin.execute("UPDATE audit_events SET action = 'tampered' WHERE id = $1", event)
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="append-only"):
        await admin.execute("DELETE FROM audit_events WHERE id = $1", event)

    # Explicit, transaction-scoped opt-in for retention purges (Session 49).
    async with admin.transaction():
        await admin.execute("SET LOCAL app.audit_purge = 'on'")
        await admin.execute("DELETE FROM audit_events WHERE id = $1", event)
    assert await admin.fetchval("SELECT count(*) FROM audit_events WHERE id = $1", event) == 0


async def test_app_role_has_dml_on_identity_tables(
    admin: asyncpg.Connection, app_conn: asyncpg.Connection
) -> None:
    user = await make_user(app_conn)  # users is global (no RLS)
    org = uuid.uuid4()
    async with app_conn.transaction():
        # Tenant rows need the org's RLS context (T1.2); org creation enters it first.
        await app_conn.execute("SELECT set_config('app.organization_id', $1, true)", str(org))
        await app_conn.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'Acme', 'acme')", org
        )
        await app_conn.execute(
            "INSERT INTO memberships (id, organization_id, user_id, role_id) "
            "VALUES ($1, $2, $3, $4)",
            uuid.uuid4(),
            org,
            user,
            system_role_id(SystemRole.OWNER),
        )
        count = await app_conn.fetchval(
            "SELECT count(*) FROM memberships WHERE organization_id = $1", org
        )
    assert count == 1
