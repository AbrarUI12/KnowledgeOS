"""KB/document access rules (T2.1, S12): pure-function and property tests."""

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.auth.authorization import RequestContext
from app.auth.kb_access import (
    AclRule,
    can_manage,
    can_query,
    can_view,
    effective_access_principals,
    widening_entries,
)
from app.auth.permissions import SYSTEM_ROLE_PERMISSIONS, Permission, SystemRole
from app.domain.enums import AclPermission, PrincipalType, Visibility

pytestmark = pytest.mark.unit

ORG = uuid.uuid4()
GROUP = uuid.uuid4()


def ctx(role: SystemRole = SystemRole.MEMBER, groups: tuple[uuid.UUID, ...] = ()) -> RequestContext:
    return RequestContext(
        user_id=uuid.uuid4(),
        organization_id=ORG,
        role=role.value,
        permissions=SYSTEM_ROLE_PERMISSIONS[role],
        group_ids=frozenset(groups),
    )


def rule(ptype: PrincipalType, pid: object, perm: AclPermission = AclPermission.QUERY) -> AclRule:
    return AclRule(ptype, str(pid), perm)


def test_organization_kb_is_queryable_by_every_member() -> None:
    for role in SystemRole:
        assert can_query(ctx(role), Visibility.ORGANIZATION, []) is True


def test_restricted_kb_needs_a_matching_acl_entry() -> None:
    alice = ctx()
    assert can_query(alice, Visibility.RESTRICTED, []) is False
    assert can_query(alice, Visibility.RESTRICTED, [rule(PrincipalType.USER, alice.user_id)])
    in_group = ctx(groups=(GROUP,))
    assert can_query(in_group, Visibility.RESTRICTED, [rule(PrincipalType.GROUP, GROUP)])
    assert can_query(ctx(), Visibility.RESTRICTED, [rule(PrincipalType.ROLE, "member")])
    assert not can_query(ctx(), Visibility.RESTRICTED, [rule(PrincipalType.ROLE, "admin")])


def test_kb_manage_permission_sees_but_cannot_read_restricted_content() -> None:
    """Managers administer restricted KBs; reading content still needs an ACL entry, matching
    the chunk ACL tokens retrieval will use."""
    admin = ctx(SystemRole.ADMIN)
    assert can_manage(admin, []) is True
    assert can_view(admin, Visibility.RESTRICTED, []) is True
    assert can_query(admin, Visibility.RESTRICTED, []) is False


def test_manage_acl_entry_grants_management_and_reading() -> None:
    bob = ctx()
    acl = [rule(PrincipalType.USER, bob.user_id, AclPermission.MANAGE)]
    assert can_manage(bob, acl)
    assert can_query(bob, Visibility.RESTRICTED, acl)


@given(
    role=st.sampled_from(list(SystemRole)),
    visibility=st.sampled_from(list(Visibility)),
    on_acl=st.booleans(),
    acl_perm=st.sampled_from(list(AclPermission)),
)
def test_access_invariants(
    role: SystemRole, visibility: Visibility, on_acl: bool, acl_perm: AclPermission
) -> None:
    caller = ctx(role)
    acl = [rule(PrincipalType.USER, caller.user_id, acl_perm)] if on_acl else []
    query, view, manage = (
        can_query(caller, visibility, acl),
        can_view(caller, visibility, acl),
        can_manage(caller, acl),
    )

    assert view == (query or manage)  # visible exactly when readable or manageable
    assert not query or Permission.QUERY_EXECUTE in caller.permissions
    if visibility is Visibility.RESTRICTED:
        assert query == on_acl  # restricted content only through the ACL
    assert manage == (
        Permission.KB_MANAGE in caller.permissions or (on_acl and acl_perm is AclPermission.MANAGE)
    )


def test_document_acl_may_narrow_but_not_widen_a_restricted_kb() -> None:
    hr, eng = uuid.uuid4(), uuid.uuid4()
    kb_acl = [
        rule(PrincipalType.GROUP, hr),
        rule(PrincipalType.ROLE, "admin", AclPermission.MANAGE),
    ]

    narrower = [rule(PrincipalType.GROUP, hr)]
    assert widening_entries(Visibility.RESTRICTED, kb_acl, narrower) == []
    wider = [rule(PrincipalType.GROUP, hr), rule(PrincipalType.GROUP, eng)]
    assert widening_entries(Visibility.RESTRICTED, kb_acl, wider) == [
        rule(PrincipalType.GROUP, eng)
    ]
    # Any document ACL narrows an organization-wide KB.
    assert widening_entries(Visibility.ORGANIZATION, [], wider) == []


def test_effective_principals_prefer_document_then_kb_then_org() -> None:
    hr, alice = uuid.uuid4(), uuid.uuid4()
    kb_acl = [rule(PrincipalType.GROUP, hr), rule(PrincipalType.USER, alice, AclPermission.MANAGE)]

    assert effective_access_principals(ORG, Visibility.ORGANIZATION, kb_acl) == [f"org:{ORG}"]
    assert effective_access_principals(ORG, Visibility.RESTRICTED, kb_acl) == sorted(
        [f"group:{hr}", f"user:{alice}"]
    )
    doc_acl = [rule(PrincipalType.USER, alice)]
    assert effective_access_principals(ORG, Visibility.RESTRICTED, kb_acl, doc_acl) == [
        f"user:{alice}"
    ]
