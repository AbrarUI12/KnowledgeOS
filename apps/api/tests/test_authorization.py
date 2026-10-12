"""Permission engine invariants (T1.2, S08): decisions always match the role table."""

import uuid

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.api.dependencies.tenancy import require_permission
from app.api.errors import Forbidden
from app.auth.authorization import RequestContext, has_permission, principal_tokens
from app.auth.permissions import SYSTEM_ROLE_PERMISSIONS, Permission, SystemRole

pytestmark = pytest.mark.unit


def _ctx(role: str, permissions: frozenset[Permission], groups: int = 0) -> RequestContext:
    return RequestContext(
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        role=role,
        permissions=permissions,
        group_ids=frozenset(uuid.uuid4() for _ in range(groups)),
    )


async def _decide(ctx: RequestContext, permission: Permission) -> bool:
    check = require_permission(permission).dependency
    try:
        assert await check(ctx) is ctx
    except Forbidden:
        return False
    return True


@given(role=st.sampled_from(list(SystemRole)), permission=st.sampled_from(list(Permission)))
async def test_system_role_decisions_match_the_role_table(
    role: SystemRole, permission: Permission
) -> None:
    ctx = _ctx(role.value, SYSTEM_ROLE_PERMISSIONS[role])
    expected = permission in SYSTEM_ROLE_PERMISSIONS[role]

    assert has_permission(ctx, permission) is expected
    assert await _decide(ctx, permission) is expected


@given(
    granted=st.frozensets(st.sampled_from(list(Permission))),
    permission=st.sampled_from(list(Permission)),
)
async def test_custom_role_decisions_match_granted_set(
    granted: frozenset[Permission], permission: Permission
) -> None:
    ctx = _ctx("custom", granted)
    assert await _decide(ctx, permission) is (permission in granted)


@given(groups=st.integers(min_value=0, max_value=5))
def test_principal_tokens_cover_user_role_org_and_every_group(groups: int) -> None:
    ctx = _ctx("member", frozenset(), groups)
    tokens = principal_tokens(ctx)

    assert tokens == sorted(tokens)
    assert len(tokens) == len(set(tokens)) == 3 + groups
    assert f"user:{ctx.user_id}" in tokens
    assert f"org:{ctx.organization_id}" in tokens
    assert "role:member" in tokens
    assert {f"group:{g}" for g in ctx.group_ids} <= set(tokens)
