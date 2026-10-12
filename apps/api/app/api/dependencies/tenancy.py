"""Tenant-context and permission dependencies (T1.2).

Org-scoped routes take the organization from the `{org_id}` path parameter or, for resources not
under /v1/organizations/{org_id}, from the `X-Organization-Id` header (the route declares either,
so OpenAPI documents it). Non-members get 404, members without the permission get 403.

    @router.get("/organizations/{org_id}/members")
    async def list_members(org_id: uuid.UUID, ctx: OrgContext): ...

    @router.post("/knowledge-bases")
    async def create_kb(
        org: OrgIdHeader, ctx: Annotated[RequestContext, require_permission(Permission.KB_CREATE)]
    ): ...
"""

import uuid
from typing import Annotated, Any

from fastapi import Depends, Request

from app.api.dependencies.auth import CurrentUser
from app.api.errors import Forbidden, NotFound, ValidationFailed
from app.api.middleware import current_request_id
from app.auth.authorization import RequestContext, has_permission
from app.auth.permissions import Permission
from app.db.session import DbSession
from app.domain.schemas.common import ORG_HEADER
from app.services.tenancy import resolve_request_context


def _organization_id(request: Request) -> uuid.UUID:
    raw = request.path_params.get("org_id") or request.headers.get(ORG_HEADER)
    if not raw:
        raise ValidationFailed(f"The {ORG_HEADER} header is required.")
    try:
        return uuid.UUID(str(raw))
    except ValueError:
        raise ValidationFailed("The organization id is not a valid UUID.") from None


async def get_request_context(
    request: Request, user: CurrentUser, session: DbSession
) -> RequestContext:
    organization_id = _organization_id(request)
    ctx = await resolve_request_context(
        session,
        user_id=user.id,
        organization_id=organization_id,
        request_id=current_request_id(request.scope),
    )
    if ctx is None:
        raise NotFound("The organization was not found.")
    return ctx


OrgContext = Annotated[RequestContext, Depends(get_request_context)]


def require_permission(permission: Permission) -> Any:
    """Dependency for `Annotated[RequestContext, require_permission(...)]`; 403 if missing."""

    async def check(ctx: OrgContext) -> RequestContext:
        if not has_permission(ctx, permission):
            raise Forbidden(details={"permission": permission.value})
        return ctx

    return Depends(check)
