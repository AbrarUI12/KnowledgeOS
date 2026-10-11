import re

import pytest

from app.auth.permissions import (
    SYSTEM_ROLE_NAMES,
    SYSTEM_ROLE_PERMISSIONS,
    Permission,
    SystemRole,
    system_role_id,
)

P = Permission


@pytest.mark.unit
def test_every_system_role_is_defined() -> None:
    assert set(SYSTEM_ROLE_PERMISSIONS) == set(SystemRole)
    assert set(SYSTEM_ROLE_NAMES) == set(SystemRole)


@pytest.mark.unit
def test_permission_strings_have_resource_action_format() -> None:
    for permission in Permission:
        assert re.fullmatch(r"[a-z_]+\.[a-z_]+", permission.value), permission


@pytest.mark.unit
def test_owner_has_every_permission() -> None:
    assert SYSTEM_ROLE_PERMISSIONS[SystemRole.OWNER] == frozenset(Permission)


@pytest.mark.unit
def test_admin_cannot_change_org_settings_or_model_policy() -> None:
    admin = SYSTEM_ROLE_PERMISSIONS[SystemRole.ADMIN]
    assert P.ORG_MANAGE not in admin
    assert P.MODEL_POLICY_MANAGE not in admin
    assert {P.MEMBERS_MANAGE, P.KB_MANAGE, P.AUDIT_READ, P.API_KEYS_MANAGE} <= admin


@pytest.mark.unit
def test_knowledge_manager_curates_documents_but_cannot_manage_people() -> None:
    km = SYSTEM_ROLE_PERMISSIONS[SystemRole.KNOWLEDGE_MANAGER]
    assert {P.DOCUMENT_UPLOAD, P.DOCUMENT_PUBLISH, P.DOCUMENT_DELETE} <= km
    assert P.MEMBERS_MANAGE not in km
    assert P.KB_MANAGE not in km


@pytest.mark.unit
@pytest.mark.parametrize("role", [SystemRole.MEMBER, SystemRole.VIEWER])
def test_members_and_viewers_can_only_query(role: SystemRole) -> None:
    assert SYSTEM_ROLE_PERMISSIONS[role] == frozenset({P.QUERY_EXECUTE})


@pytest.mark.unit
def test_every_role_can_query() -> None:
    for perms in SYSTEM_ROLE_PERMISSIONS.values():
        assert P.QUERY_EXECUTE in perms


@pytest.mark.unit
def test_system_role_ids_are_deterministic_and_distinct() -> None:
    ids = {system_role_id(role) for role in SystemRole}
    assert len(ids) == len(SystemRole)
    assert system_role_id(SystemRole.OWNER) == system_role_id(SystemRole.OWNER)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("privileges", "table", "role"),
    [
        ("SELECT; DROP TABLE users", "users", "knowledgeos_app"),
        ("SELECT", "users; DROP TABLE users", "knowledgeos_app"),
        ("SELECT", "users", "x' OR '1'='1"),
        ("ALL PRIVILEGES", "users", "knowledgeos_app"),
    ],
)
def test_migration_grant_helpers_reject_unsafe_input(
    privileges: str, table: str, role: str
) -> None:
    from app.db.migration_helpers import _checked

    with pytest.raises(ValueError, match="invalid"):
        _checked(privileges, table, role)
