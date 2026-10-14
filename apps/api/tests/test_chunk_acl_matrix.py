"""ACL materialization matrix (S23): the tokens written onto chunks grant exactly the access the
KB/document rules grant. For every visibility, KB ACL, (non-widening) document ACL and caller with
`query.execute`, a chunk is matched by the caller's tokens iff the caller may read the document's
content: KB query access and, if the document has its own ACL, an entry for the caller."""

import uuid

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.auth.authorization import RequestContext, principal_tokens
from app.auth.kb_access import (
    AclRule,
    caller_principals,
    can_query,
    effective_access_principals,
    widening_entries,
)
from app.auth.permissions import Permission
from app.domain.enums import AclPermission, PrincipalType, Visibility

pytestmark = pytest.mark.unit

ORG = uuid.UUID("01900000-0000-7000-8000-000000000001")
USERS = [uuid.UUID(f"01900000-0000-7000-8000-00000000010{i}") for i in range(3)]
GROUPS = [uuid.UUID(f"01900000-0000-7000-8000-00000000020{i}") for i in range(3)]
ROLES = ["owner", "admin", "member", "viewer"]

principals = st.one_of(
    st.tuples(st.just(PrincipalType.USER), st.sampled_from([str(u) for u in USERS])),
    st.tuples(st.just(PrincipalType.GROUP), st.sampled_from([str(g) for g in GROUPS])),
    st.tuples(st.just(PrincipalType.ROLE), st.sampled_from(ROLES)),
)
rules = st.builds(
    lambda principal, permission: AclRule(principal[0], principal[1], permission),
    principals,
    st.sampled_from(list(AclPermission)),
)
callers = st.builds(
    lambda user, role, groups: RequestContext(
        user_id=user,
        organization_id=ORG,
        role=role,
        permissions=frozenset({Permission.QUERY_EXECUTE}),
        group_ids=frozenset(groups),
    ),
    st.sampled_from(USERS),
    st.sampled_from(ROLES),
    st.sets(st.sampled_from(GROUPS)),
)


def may_read_content(
    ctx: RequestContext, visibility: Visibility, kb_acl: list[AclRule], document_acl: list[AclRule]
) -> bool:
    mine = caller_principals(ctx)
    document_ok = not document_acl or any(rule.principal in mine for rule in document_acl)
    return can_query(ctx, visibility, kb_acl) and document_ok


@settings(max_examples=500)
@given(
    visibility=st.sampled_from(list(Visibility)),
    kb_acl=st.lists(rules, max_size=4),
    document_acl=st.lists(rules, max_size=3),
    ctx=callers,
)
def test_materialized_tokens_match_the_access_rules(
    visibility: Visibility, kb_acl: list[AclRule], document_acl: list[AclRule], ctx: RequestContext
) -> None:
    # Document ACLs that would widen a restricted KB are rejected at write time.
    if widening_entries(visibility, kb_acl, document_acl):
        document_acl = [r for r in document_acl if r.principal in {k.principal for k in kb_acl}]

    tokens = effective_access_principals(ORG, visibility, kb_acl, document_acl)
    matched = bool(set(tokens) & set(principal_tokens(ctx)))

    assert matched == may_read_content(ctx, visibility, kb_acl, document_acl)


@given(document_acl=st.lists(rules, min_size=1, max_size=3), ctx=callers)
def test_a_document_acl_only_ever_narrows(document_acl: list[AclRule], ctx: RequestContext) -> None:
    organization_wide = effective_access_principals(ORG, Visibility.ORGANIZATION, [])
    narrowed = effective_access_principals(ORG, Visibility.ORGANIZATION, [], document_acl)
    if set(narrowed) & set(principal_tokens(ctx)):
        assert set(organization_wide) & set(principal_tokens(ctx))
