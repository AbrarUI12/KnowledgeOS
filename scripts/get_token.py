"""Get an OIDC access token for local development (Task T1.8).

Usage:
    uv --directory apps/api run python ../../scripts/get_token.py alice

This performs a password grant against the dev Keycloak realm to obtain
an access token for one of the 4 predefined dev users. It refuses to run
if the OIDC issuer is not localhost, to prevent accidental use against
staging or production environments.
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlsplit

# Load environment from .env at repo root
ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    """Read .env.example then .env (if present) from repo root."""
    env: dict[str, str] = {}
    for name in (".env.example", ".env"):
        path = ROOT / name
        if not path.exists():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


ENV = load_env()

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def is_local_issuer(issuer: str) -> bool:
    """True only if the issuer's *host* is loopback (not e.g. http://localhost.evil.com)."""
    try:
        return urlsplit(issuer).hostname in LOCAL_HOSTS
    except ValueError:
        return False


def _decode_token_summary(parts: list[str], email: str) -> str | None:
    """Best-effort decode of JWT claims for a human-readable one-line summary."""
    import base64
    import json

    if len(parts) < 2:
        return None
    payload_b64 = parts[1]
    payload_b64 += "=" * (4 - len(payload_b64) % 4)
    try:
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
    except (ValueError, TypeError):
        return None
    aud = claims.get("aud", "?")
    sub = claims.get("sub", "?")
    exp = claims.get("exp", "?")
    return f"Token for {email} (aud={aud}, sub={str(sub)[:8]}..., exp={exp})"


# Dev users matching Session 07 / Session 25 seed data
DEV_USERS = {
    "alice": "alice@acme.test",
    "bob": "bob@acme.test",
    "hana": "hana@acme.test",
    "carol": "carol@globex.test",
}

DEV_PASSWORDS = {
    "alice@acme.test": "alice-dev-password",
    "bob@acme.test": "bob-dev-password",
    "hana@acme.test": "hana-dev-password",
    "carol@globex.test": "carol-dev-password",
}


def get_token(username: str) -> str:
    """Perform a password grant and return the access token."""
    import httpx

    issuer = ENV.get("OIDC_ISSUER", "http://localhost:8080/realms/knowledgeos")
    client_id = ENV.get("OIDC_CLI_CLIENT_ID", "knowledgeos-cli")

    # Safety check: refuse non-localhost issuers
    if not is_local_issuer(issuer):
        print(
            f"ERROR: OIDC_ISSUER ({issuer}) is not a localhost address. "
            "This script is for local development only.",
            file=sys.stderr,
        )
        sys.exit(1)

    email = DEV_USERS.get(username)
    if email is None:
        print(
            f"ERROR: unknown user '{username}'. Available: {', '.join(sorted(DEV_USERS))}",
            file=sys.stderr,
        )
        sys.exit(1)

    password = DEV_PASSWORDS[email]

    token_url = f"{issuer}/protocol/openid-connect/token"
    resp = httpx.post(
        token_url,
        data={
            "grant_type": "password",
            "client_id": client_id,
            "username": email,
            "password": password,
            "scope": "openid",
        },
        timeout=10,
    )
    resp.raise_for_status()
    token = resp.json()["access_token"]

    # Print with brief summary

    # Decode JWT payload (second segment) for display
    parts = token.split(".")
    summary = _decode_token_summary(parts, email)
    if summary:
        print(summary, file=sys.stderr)

    print(token)
    return token


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] in ("-h", "--help"):
        print(f"Usage: python {sys.argv[0]} <username>")
        print(f"Available users: {', '.join(sorted(DEV_USERS))}")
        sys.exit(0 if "--help" in sys.argv or "-h" in sys.argv else 1)

    get_token(sys.argv[1])


if __name__ == "__main__":
    main()
