"""Contract: OIDC access-token verification (ADR-003, T1.0). Implementation: Claude T1.1."""

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class VerifiedToken(BaseModel):
    model_config = ConfigDict(frozen=True)

    issuer: str
    subject: str
    email: str | None = None
    name: str | None = None
    claims: dict[str, Any] = {}


class TokenInvalidError(Exception):
    """Signature, issuer, audience, expiry or algorithm check failed (→ 401)."""


class IdentityProviderUnavailableError(Exception):
    """Discovery/JWKS couldn't be fetched and no valid cached key exists (→ 503)."""


@runtime_checkable
class IdentityVerifier(Protocol):
    async def verify(self, token: str) -> VerifiedToken: ...
