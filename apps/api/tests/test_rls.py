"""Tenant isolation at the repository level: row-level security as the runtime role (T1.2, S08).

Every check runs as `knowledgeos_app` (NOBYPASSRLS, owns nothing). Setup uses the superuser
`admin` connection, because forced RLS binds the owner role too.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import asyncpg
import pytest
from sqlalchemy import text

from app.auth.permissions import SystemRole, system_role_id
from app.core.config import Settings
from app.db.session import create_engine, create_sessionmaker
from app.db.tenant import tenant_session

pytestmark = pytest.mark.integration

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


def _dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


@pytest.fixture
async def admin(admin_dsn: str, migrated_settings: Settings) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(admin_dsn)
    try:
        yield conn
    finally:
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


@dataclass(frozen=True)
class Tenant:
    org: uuid.UUID
    user: uuid.UUID
    group: uuid.UUID
    custom_role: uuid.UUID
    invitation: uuid.UUID
    audit_event: uuid.UUID


async def _seed_tenant(admin: asyncpg.Connection, slug: str) -> Tenant:
    org = await admin.fetchval(
        "INSERT INTO organizations (id, name, slug) VALUES ($1, $2, $3) RETURNING id",
        uuid.uuid4(),
        slug.title(),
        slug,
    )
    user = await admin.fetchval(
        "INSERT INTO users (id, issuer, external_subject, email) "
        "VALUES ($1, 'http://issuer.test', $2, $3) RETURNING id",
        uuid.uuid4(),
        f"{slug}-user",
        f"user@{slug}.test",
    )
    await admin.execute(
        "INSERT INTO memberships (id, organization_id, user_id, role_id) VALUES ($1, $2, $3, $4)",
        uuid.uuid4(),
        org,
        user,
        system_role_id(SystemRole.MEMBER),
    )
    group = await admin.fetchval(
        "INSERT INTO groups (id, organization_id, name) VALUES ($1, $2, 'HR') RETURNING id",
        uuid.uuid4(),
        org,
    )
    await admin.execute(
        "INSERT INTO group_memberships (group_id, user_id, organization_id) VALUES ($1, $2, $3)",
        group,
        user,
        org,
    )
    custom_role = await admin.fetchval(
        "INSERT INTO roles (id, organization_id, key, name) VALUES ($1, $2, 'auditor', 'Auditor') "
        "RETURNING id",
        uuid.uuid4(),
        org,
    )
    await admin.execute(
        "INSERT INTO role_permissions (role_id, permission, organization_id) "
        "VALUES ($1, 'audit.read', $2)",
        custom_role,
        org,
    )
    invitation = await admin.fetchval(
        "INSERT INTO invitations (id, organization_id, email, role_id, token_hash, invited_by, "
        "expires_at) VALUES ($1, $2, 'new@x.test', $3, $4, $5, now() + interval '1 day') "
        "RETURNING id",
        uuid.uuid4(),
        org,
        system_role_id(SystemRole.MEMBER),
        uuid.uuid4().hex,
        user,
    )
    audit_event = await admin.fetchval(
        "INSERT INTO audit_events (id, organization_id, actor_type, action, resource_type) "
        "VALUES ($1, $2, 'system', 'org.created', 'organization') RETURNING id",
        uuid.uuid4(),
        org,
    )
    return Tenant(org, user, group, custom_role, invitation, audit_event)


@pytest.fixture
async def tenants(admin: asyncpg.Connection) -> tuple[Tenant, Tenant]:
    return await _seed_tenant(admin, "acme"), await _seed_tenant(admin, "globex")


@asynccontextmanager
async def context(
    conn: asyncpg.Connection, org: uuid.UUID | None, user: uuid.UUID | None = None
) -> AsyncIterator[asyncpg.Connection]:
    """A transaction with the same transaction-local settings app.db.tenant writes."""
    async with conn.transaction():
        await conn.execute(
            "SELECT set_config('app.organization_id', $1, true), "
            "set_config('app.user_id', $2, true)",
            str(org) if org else "",
            str(user) if user else "",
        )
        yield conn


async def _count_all(conn: asyncpg.Connection) -> dict[str, int]:
    counts = {}
    for table in (*TENANT_TABLES, "organizations"):
        # Table names come from the fixed tuple above.
        counts[table] = await conn.fetchval(f"SELECT count(*) FROM {table}")  # noqa: S608
    return counts


# --------------------------------------------------------------------------- reading


async def test_other_orgs_rows_are_invisible_even_by_exact_id(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, globex = tenants
    async with context(app_conn, acme.org, acme.user) as c:
        assert await c.fetchval("SELECT count(*) FROM groups WHERE id = $1", globex.group) == 0
        assert (
            await c.fetchval("SELECT count(*) FROM invitations WHERE id = $1", globex.invitation)
            == 0
        )
        assert (
            await c.fetchval("SELECT count(*) FROM audit_events WHERE id = $1", globex.audit_event)
            == 0
        )
        assert await c.fetchval("SELECT count(*) FROM roles WHERE id = $1", globex.custom_role) == 0
        assert await c.fetchval("SELECT count(*) FROM organizations WHERE id = $1", globex.org) == 0
        assert (
            await c.fetchval(
                "SELECT count(*) FROM memberships WHERE organization_id = $1", globex.org
            )
            == 0
        )
        # ...while its own rows are visible.
        assert await c.fetchval("SELECT count(*) FROM groups WHERE id = $1", acme.group) == 1


async def test_no_context_sees_no_tenant_rows(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    counts = await _count_all(app_conn)
    # System roles (organization_id IS NULL) and their permissions are global by design.
    system_roles = len(SystemRole)
    assert counts.pop("roles") == system_roles
    assert counts.pop("role_permissions") > 0
    assert set(counts.values()) == {0}, counts


async def test_context_does_not_leak_to_the_next_transaction(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, _ = tenants
    async with context(app_conn, acme.org, acme.user) as c:
        assert await c.fetchval("SELECT count(*) FROM groups") == 1
    # Same pooled connection, new transaction: the GUC now reads '' (not NULL) and must still
    # match nothing rather than erroring.
    assert await app_conn.fetchval("SELECT count(*) FROM groups") == 0
    assert await app_conn.fetchval("SELECT count(*) FROM memberships") == 0


async def test_session_level_set_is_not_how_context_is_set(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    """Documented pitfall: only set_config(..., true) is transaction-scoped."""
    acme, _ = tenants
    async with app_conn.transaction():
        await app_conn.execute("SELECT set_config('app.organization_id', $1, true)", str(acme.org))
    assert await app_conn.fetchval("SELECT current_setting('app.organization_id', true)") == ""


async def test_user_context_shows_only_own_memberships_and_orgs(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, globex = tenants
    async with context(app_conn, None, acme.user) as c:
        memberships = await c.fetch("SELECT organization_id, user_id FROM memberships")
        assert [(m["organization_id"], m["user_id"]) for m in memberships] == [
            (acme.org, acme.user)
        ]
        assert [r["id"] for r in await c.fetch("SELECT id FROM organizations")] == [acme.org]
        # Custom roles of the user's orgs are readable (for /v1/me), other orgs' are not.
        role_ids = {r["id"] for r in await c.fetch("SELECT id FROM roles")}
        assert acme.custom_role in role_ids
        assert globex.custom_role not in role_ids
        # But nothing else of the org is visible without the org context.
        assert await c.fetchval("SELECT count(*) FROM groups") == 0


async def test_suspended_membership_does_not_reveal_the_org(
    admin: asyncpg.Connection, app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, _ = tenants
    await admin.execute("UPDATE memberships SET status = 'suspended' WHERE user_id = $1", acme.user)
    async with context(app_conn, None, acme.user) as c:
        assert await c.fetchval("SELECT count(*) FROM organizations") == 0


# --------------------------------------------------------------------------- writing


async def test_insert_into_another_org_is_rejected(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, globex = tenants
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        async with context(app_conn, acme.org, acme.user) as c:
            await c.execute(
                "INSERT INTO groups (id, organization_id, name) VALUES ($1, $2, 'Planted')",
                uuid.uuid4(),
                globex.org,
            )


async def test_insert_without_context_is_rejected(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, _ = tenants
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        await app_conn.execute(
            "INSERT INTO groups (id, organization_id, name) VALUES ($1, $2, 'Orphan')",
            uuid.uuid4(),
            acme.org,
        )


async def test_rows_cannot_be_moved_to_another_org(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, globex = tenants
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        async with context(app_conn, acme.org, acme.user) as c:
            await c.execute(
                "UPDATE groups SET organization_id = $1 WHERE id = $2", globex.org, acme.group
            )


async def test_other_orgs_rows_cannot_be_updated_or_deleted(
    admin: asyncpg.Connection, app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, globex = tenants
    async with context(app_conn, acme.org, acme.user) as c:
        assert await c.execute("UPDATE groups SET name = 'x' WHERE id = $1", globex.group) == (
            "UPDATE 0"
        )
        assert await c.execute("DELETE FROM groups WHERE id = $1", globex.group) == "DELETE 0"
        # A member's own-membership read access doesn't extend to writes in another org.
        assert await c.execute(
            "UPDATE memberships SET status = 'active' WHERE organization_id = $1", globex.org
        ) == ("UPDATE 0")
    assert await admin.fetchval("SELECT name FROM groups WHERE id = $1", globex.group) == "HR"


async def test_system_roles_are_read_only_for_the_app(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, _ = tenants
    owner_role = system_role_id(SystemRole.OWNER)
    async with context(app_conn, acme.org, acme.user) as c:
        assert await c.execute("UPDATE roles SET name = 'pwned' WHERE id = $1", owner_role) == (
            "UPDATE 0"
        )
        assert (
            await c.execute("DELETE FROM role_permissions WHERE role_id = $1", owner_role)
            == "DELETE 0"
        )
    with pytest.raises(asyncpg.InsufficientPrivilegeError, match="row-level security"):
        async with context(app_conn, acme.org, acme.user) as c:
            await c.execute(
                "INSERT INTO role_permissions (role_id, permission, organization_id) "
                "VALUES ($1, 'audit.read', NULL)",
                system_role_id(SystemRole.VIEWER),
            )


async def test_new_org_can_be_created_by_entering_its_context_first(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    """The org-creation pattern T1.3 uses: choose the id, enter its context, insert."""
    acme, _ = tenants
    new_org = uuid.uuid4()
    async with context(app_conn, new_org, acme.user) as c:
        await c.execute(
            "INSERT INTO organizations (id, name, slug) VALUES ($1, 'New', 'new-org')", new_org
        )
        await c.execute(
            "INSERT INTO memberships (id, organization_id, user_id, role_id) "
            "VALUES ($1, $2, $3, $4)",
            uuid.uuid4(),
            new_org,
            acme.user,
            system_role_id(SystemRole.OWNER),
        )
    async with context(app_conn, None, acme.user) as c:
        orgs = {r["id"] for r in await c.fetch("SELECT id FROM organizations")}
    assert orgs == {acme.org, new_org}


# --------------------------------------------------------------------------- role safety


async def test_app_role_cannot_bypass_rls(
    app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    role = await app_conn.fetchrow(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    )
    assert role is not None
    assert (role["rolsuper"], role["rolbypassrls"]) == (False, False)
    assert (
        await app_conn.fetchval(
            "SELECT count(*) FROM pg_class c JOIN pg_roles r ON r.oid = c.relowner "
            "WHERE r.rolname = current_user AND c.relnamespace = 'public'::regnamespace"
        )
        == 0
    )
    # row_security = off makes queries that RLS would filter fail instead of bypassing it.
    await app_conn.execute("SET row_security = off")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.fetchval("SELECT count(*) FROM groups")
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        await app_conn.execute("ALTER TABLE groups DISABLE ROW LEVEL SECURITY")


async def test_every_tenant_table_has_forced_rls(admin: asyncpg.Connection) -> None:
    """Meta-test guarding all future migrations: an `organization_id` column requires forced RLS
    and at least one policy (use migration_helpers.enable_tenant_rls)."""
    rows = await admin.fetch(
        """
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid) AS policies
        FROM pg_class c
        WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
          AND (c.relname = 'organizations' OR EXISTS (
                SELECT 1 FROM pg_attribute a
                WHERE a.attrelid = c.oid AND a.attname = 'organization_id' AND NOT a.attisdropped))
        """
    )
    assert {r["relname"] for r in rows} >= {*TENANT_TABLES, "organizations"}
    unprotected = [
        r["relname"]
        for r in rows
        if not (r["relrowsecurity"] and r["relforcerowsecurity"] and r["policies"] > 0)
    ]
    assert unprotected == []


# --------------------------------------------------------------------------- helper


async def test_tenant_session_helper_scopes_workers_to_one_org(
    migrated_settings: Settings, tenants: tuple[Tenant, Tenant]
) -> None:
    acme, _ = tenants
    engine = create_engine(migrated_settings)
    try:
        sessionmaker = create_sessionmaker(engine)
        async with tenant_session(sessionmaker, acme.org) as session:
            groups = (await session.execute(text("SELECT id FROM groups"))).scalars().all()
        assert groups == [acme.group]
        async with sessionmaker() as session, session.begin():
            assert (await session.execute(text("SELECT count(*) FROM groups"))).scalar_one() == 0
    finally:
        await engine.dispose()


async def test_knowledge_tables_are_isolated_per_org(
    admin: asyncpg.Connection, app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    """T2.1: knowledge rows of org B are invisible and unwritable in org A's context."""
    acme, globex = tenants
    kb = await admin.fetchval(
        "INSERT INTO knowledge_bases (id, organization_id, name, slug) "
        "VALUES ($1, $2, 'Secrets', 'secrets') RETURNING id",
        uuid.uuid4(),
        globex.org,
    )
    source = await admin.fetchval(
        "INSERT INTO data_sources (id, organization_id, knowledge_base_id, type, name) "
        "VALUES ($1, $2, $3, 'upload', 'Uploads') RETURNING id",
        uuid.uuid4(),
        globex.org,
        kb,
    )
    await admin.execute(
        "INSERT INTO documents (id, organization_id, knowledge_base_id, source_id, title) "
        "VALUES ($1, $2, $3, $4, 'Salaries')",
        uuid.uuid4(),
        globex.org,
        kb,
        source,
    )
    await admin.execute(
        "INSERT INTO outbox_events (id, organization_id, event_type, aggregate_type, aggregate_id) "
        "VALUES ($1, $2, 'acl.changed', 'knowledge_base', $3)",
        uuid.uuid4(),
        globex.org,
        str(kb),
    )

    async with context(app_conn, acme.org, acme.user) as c:
        for table in ("knowledge_bases", "data_sources", "documents", "outbox_events"):
            assert await c.fetchval(f"SELECT count(*) FROM {table}") == 0, table  # noqa: S608
    # A composite FK can't point an org-A document at org B's knowledge base either.
    with pytest.raises((asyncpg.ForeignKeyViolationError, asyncpg.InsufficientPrivilegeError)):
        async with context(app_conn, acme.org, acme.user) as c:
            await c.execute(
                "INSERT INTO documents (id, organization_id, knowledge_base_id, source_id, title) "
                "VALUES ($1, $2, $3, $4, 'Planted')",
                uuid.uuid4(),
                acme.org,
                kb,
                source,
            )


async def test_active_version_must_belong_to_the_document_and_org(
    admin: asyncpg.Connection, app_conn: asyncpg.Connection, tenants: tuple[Tenant, Tenant]
) -> None:
    """Review #25 (HIGH): documents.active_version_id can't point at another document's or another
    organization's version, even though FK checks bypass RLS on the referenced row."""
    acme, globex = tenants

    async def make_doc(org: uuid.UUID) -> tuple[uuid.UUID, uuid.UUID]:
        kb = await admin.fetchval(
            "INSERT INTO knowledge_bases (id, organization_id, name, slug) "
            "VALUES ($1, $2, 'K', $3) RETURNING id",
            uuid.uuid4(),
            org,
            f"k-{uuid.uuid4().hex[:6]}",
        )
        source = await admin.fetchval(
            "INSERT INTO data_sources (id, organization_id, knowledge_base_id, type, name) "
            "VALUES ($1, $2, $3, 'upload', 'U') RETURNING id",
            uuid.uuid4(),
            org,
            kb,
        )
        doc = await admin.fetchval(
            "INSERT INTO documents (id, organization_id, knowledge_base_id, source_id, title) "
            "VALUES ($1, $2, $3, $4, 'D') RETURNING id",
            uuid.uuid4(),
            org,
            kb,
            source,
        )
        version = await admin.fetchval(
            "INSERT INTO document_versions (id, organization_id, document_id, version_number) "
            "VALUES ($1, $2, $3, 1) RETURNING id",
            uuid.uuid4(),
            org,
            doc,
        )
        return doc, version

    doc_a, version_a = await make_doc(acme.org)
    _, other_version_a = await make_doc(acme.org)
    _, version_b = await make_doc(globex.org)

    async with context(app_conn, acme.org, acme.user) as c:
        await c.execute(
            "UPDATE documents SET active_version_id = $1 WHERE id = $2", version_a, doc_a
        )

    for foreign in (other_version_a, version_b):
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with context(app_conn, acme.org, acme.user) as c:
                await c.execute(
                    "UPDATE documents SET active_version_id = $1 WHERE id = $2", foreign, doc_a
                )
