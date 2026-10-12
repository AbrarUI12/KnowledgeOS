"""Request authorization: tenant context, permission checks and ACL principal tokens (S08).

Layers (ADR-004): permissions decide *what* a member may do; RLS decides *which rows* exist for
the request; chunk ACLs (`principal_tokens`, Session 23) decide *which content* within the org.
"""

import uuid
from dataclasses import dataclass

from app.auth.permissions import Permission


@dataclass(frozen=True, slots=True)
class RequestContext:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    role: str
    permissions: frozenset[Permission]
    group_ids: frozenset[uuid.UUID]
    request_id: str | None = None


def has_permission(ctx: RequestContext, permission: Permission) -> bool:
    return permission in ctx.permissions


def principal_tokens(ctx: RequestContext) -> list[str]:
    """ACL tokens identifying the caller, matched against chunk `access_principals` (S23).

    Sorted for deterministic SQL parameters and cache keys.
    """
    return sorted(
        {
            f"user:{ctx.user_id}",
            f"role:{ctx.role}",
            f"org:{ctx.organization_id}",
            *(f"group:{g}" for g in ctx.group_ids),
        }
    )
