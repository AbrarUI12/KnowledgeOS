"""Authentication dependency (T1.1): bearer token → verified identity → provisioned user.

Tenant context and permissions are layered on top in `app/api/dependencies/tenancy.py` (T1.2).
"""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError, Forbidden, ServiceUnavailable, Unauthorized
from app.db.session import get_db
from app.db.tenant import set_tenant_context
from app.providers.identity.base import (
    IdentityProviderUnavailableError,
    IdentityVerifier,
    TokenInvalidError,
)
from app.services.users import AuthenticatedUser, provision_user

_WWW_AUTHENTICATE = {"WWW-Authenticate": 'Bearer realm="knowledgeos"'}


class BearerUnauthorized(Unauthorized):
    """401 that also tells clients which scheme to use (RFC 6750)."""

    headers = _WWW_AUTHENTICATE


# auto_error=False: we raise our own envelope (with WWW-Authenticate) instead of FastAPI's 403.
# Declaring the scheme publishes `bearerAuth` in OpenAPI for the generated client.
_bearer = HTTPBearer(auto_error=False, scheme_name="bearerAuth", description="OIDC access token")


def get_identity_verifier(request: Request) -> IdentityVerifier:
    verifier: IdentityVerifier = request.app.state.identity_verifier
    return verifier


def require_bearer_token(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> str:
    """Rejects requests without a token before any IdP call or database transaction starts."""
    if credentials is None or not credentials.credentials.strip():
        raise BearerUnauthorized("A bearer token is required.")
    return credentials.credentials.strip()


async def get_current_user(
    request: Request,
    # Declared first: FastAPI resolves dependencies in order, so a missing token is a cheap 401.
    token: Annotated[str, Depends(require_bearer_token)],
    verifier: Annotated[IdentityVerifier, Depends(get_identity_verifier)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthenticatedUser:
    try:
        verified = await verifier.verify(token)
    except TokenInvalidError as exc:
        raise BearerUnauthorized("The access token is invalid or expired.") from exc
    except IdentityProviderUnavailableError as exc:
        raise ServiceUnavailable("The identity provider is unavailable.") from exc

    interval = timedelta(seconds=request.app.state.settings.user_last_seen_write_interval_seconds)
    user = await provision_user(session, verified, last_seen_interval=interval)
    if not user.is_active:
        raise Forbidden("This account is disabled.")
    # RLS user context: the caller's own memberships and organizations become visible.
    await set_tenant_context(session, None, user.id)
    return user


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]

__all__ = ["AppError", "CurrentUser", "get_current_user", "get_identity_verifier"]
