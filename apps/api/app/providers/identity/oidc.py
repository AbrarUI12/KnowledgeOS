"""OIDC access-token verifier (T1.1, plan §5.6, ADR-003).

Checks, in order: compact JWS shape → header `alg` in the allowlist (never `none`, never HMAC) →
signing key by `kid` from the issuer's JWKS (cached; one rate-limited refresh on an unknown `kid`
so key rotation works without restarts) → signature → `iss` == configured issuer → `aud` contains
the configured audience → `exp` / `nbf` / `iat` with small leeway → non-empty `sub`.

Any failure raises `TokenInvalidError` (→ 401). If the identity provider can't be reached and no
usable cached key exists, `IdentityProviderUnavailableError` (→ 503). Error messages are safe to log
but never include the token.
"""

import asyncio
import time
from typing import Any

import httpx
import jwt
from jwt import PyJWK, PyJWKSet
from jwt.exceptions import InvalidTokenError, PyJWKError, PyJWKSetError

from app.core.config import Settings
from app.core.logging import get_logger
from app.providers.identity.base import (
    IdentityProviderUnavailableError,
    TokenInvalidError,
    VerifiedToken,
)

logger = get_logger(__name__)

_ASYMMETRIC_ALGORITHMS = frozenset(
    {"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"}
)


class OIDCVerifier:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        unsafe = set(settings.oidc_algorithms) - _ASYMMETRIC_ALGORITHMS
        if unsafe:
            raise ValueError(f"only asymmetric JWT algorithms are allowed, got {sorted(unsafe)}")
        # Exact string, never normalized: `iss` must match it byte for byte (Auth0 issuers end in
        # "/", Keycloak's don't). Only the discovery URL is built from a slash-trimmed copy.
        self._issuer = settings.oidc_issuer
        self._audience = settings.oidc_audience
        self._algorithms = list(settings.oidc_algorithms)
        self._leeway = settings.oidc_leeway_seconds
        self._cache_seconds = settings.oidc_jwks_cache_seconds
        self._min_refresh_seconds = settings.oidc_jwks_min_refresh_seconds
        self._configured_jwks_url = settings.oidc_jwks_url
        self._claim_namespace = settings.oidc_claim_namespace or None
        self._http = http
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at = 0.0
        self._last_refresh_attempt = 0.0
        self._last_refresh_failed = False
        self._lock = asyncio.Lock()

    async def verify(self, token: str) -> VerifiedToken:
        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise TokenInvalidError("malformed token") from exc

        alg = header.get("alg")
        if alg not in self._algorithms:
            raise TokenInvalidError("token algorithm not allowed")
        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            raise TokenInvalidError("token has no key id")

        key = await self._signing_key(kid)
        if key.algorithm_name and key.algorithm_name != alg:
            # Prevents algorithm confusion: the header can't pick a different algorithm than
            # the one the published key is for.
            raise TokenInvalidError("key algorithm mismatch")
        try:
            claims: dict[str, Any] = jwt.decode(
                token,
                key=key.key,
                algorithms=[alg],
                audience=self._audience,
                issuer=self._issuer,
                leeway=self._leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except InvalidTokenError as exc:
            raise TokenInvalidError(f"token rejected: {type(exc).__name__}") from exc

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject.strip():
            raise TokenInvalidError("token has no subject")
        if self._claim_namespace:
            # Signed by our issuer like every other claim; standard claims still win.
            for claim in ("email", "email_verified", "name"):
                if claims.get(claim) is None and f"{self._claim_namespace}{claim}" in claims:
                    claims[claim] = claims[f"{self._claim_namespace}{claim}"]
        email = claims.get("email")
        name = claims.get("name") or claims.get("preferred_username")
        return VerifiedToken(
            issuer=self._issuer,
            subject=subject,
            email=email if isinstance(email, str) else None,
            name=name if isinstance(name, str) else None,
            claims=claims,
        )

    # ------------------------------------------------------------------------- JWKS cache

    async def _signing_key(self, kid: str) -> PyJWK:
        now = time.monotonic()
        if not self._keys or now - self._fetched_at > self._cache_seconds:
            await self._refresh(force=True)
        key = self._keys.get(kid)
        if key is None:
            # Unknown kid: the IdP may have rotated keys. Refresh once (rate-limited).
            await self._refresh(force=False)
            key = self._keys.get(kid)
        if key is None:
            raise TokenInvalidError("unknown signing key")
        return key

    async def _refresh(self, *, force: bool) -> None:
        async with self._lock:
            now = time.monotonic()
            if force and self._keys and now - self._fetched_at <= self._cache_seconds:
                return  # another request refreshed while we waited for the lock
            # Rate limit: unknown-kid refreshes always; forced (expiry) refreshes after a failure,
            # so an IdP outage doesn't turn every request into a blocking network call.
            if (not force or self._last_refresh_failed) and (
                now - self._last_refresh_attempt < self._min_refresh_seconds
            ):
                if not self._keys:
                    raise IdentityProviderUnavailableError("signing keys unavailable")
                return
            self._last_refresh_attempt = now
            try:
                jwks_url = self._configured_jwks_url or await self._discover_jwks_url()
                response = await self._http.get(jwks_url)
                response.raise_for_status()
                document = response.json()
                if not isinstance(document, dict):
                    raise ValueError("JWKS document is not a JSON object")
                key_set = PyJWKSet.from_dict(document)
            except (httpx.HTTPError, ValueError, PyJWKError, PyJWKSetError) as exc:
                self._last_refresh_failed = True
                logger.warning("oidc_jwks_refresh_failed", error_type=type(exc).__name__)
                if not self._keys:
                    raise IdentityProviderUnavailableError("signing keys unavailable") from exc
                return  # keep serving the last known keys
            self._keys = {k.key_id: k for k in key_set.keys if k.key_id}
            self._fetched_at = now
            self._last_refresh_failed = False

    async def _discover_jwks_url(self) -> str:
        base = self._issuer.rstrip("/")
        response = await self._http.get(f"{base}/.well-known/openid-configuration")
        response.raise_for_status()
        document = response.json()
        if not isinstance(document, dict):
            raise ValueError("discovery document is not a JSON object")
        issuer = document.get("issuer")
        if not isinstance(issuer, str) or issuer != self._issuer:
            raise ValueError("discovery document issuer mismatch")
        jwks_uri = document.get("jwks_uri")
        if not isinstance(jwks_uri, str):
            raise ValueError("discovery document has no jwks_uri")
        return jwks_uri
