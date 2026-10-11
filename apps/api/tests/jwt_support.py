"""Test helpers: a throwaway signing key, its JWKS, and a token factory (T1.1)."""

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER = "https://idp.test/realms/knowledgeos"
AUDIENCE = "knowledgeos-api"
JWKS_URL = f"{ISSUER}/protocol/openid-connect/certs"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"


@dataclass
class SigningKey:
    kid: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    private: rsa.RSAPrivateKey = field(
        default_factory=lambda: rsa.generate_private_key(public_exponent=65537, key_size=2048)
    )

    def jwk(self) -> dict[str, Any]:
        public = RSAAlgorithm.to_jwk(self.private.public_key(), as_dict=True)
        return {**public, "kid": self.kid, "alg": "RS256", "use": "sig"}


def jwks(*keys: SigningKey) -> dict[str, Any]:
    return {"keys": [k.jwk() for k in keys]}


def discovery() -> dict[str, Any]:
    return {"issuer": ISSUER, "jwks_uri": JWKS_URL}


def make_token(
    key: SigningKey,
    *,
    sub: str = "user-123",
    issuer: str = ISSUER,
    audience: str | list[str] = AUDIENCE,
    expires_in: int = 300,
    issued_offset: int = 0,
    algorithm: str = "RS256",
    kid: str | None = None,
    extra: dict[str, Any] | None = None,
) -> str:
    now = int(time.time()) + issued_offset
    claims: dict[str, Any] = {
        "iss": issuer,
        "aud": audience,
        "sub": sub,
        "iat": now,
        "exp": now + expires_in,
        "email": f"{sub}@example.test",
        "name": f"User {sub}",
        **(extra or {}),
    }
    return jwt.encode(claims, key.private, algorithm=algorithm, headers={"kid": kid or key.kid})
