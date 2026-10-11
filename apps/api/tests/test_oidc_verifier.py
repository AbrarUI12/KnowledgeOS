"""OIDCVerifier: every acceptance and rejection rule from session.md S07 (T1.1)."""

import base64
import hashlib
import hmac
import json
from collections.abc import AsyncIterator

import httpx
import pytest
import respx
from cryptography.hazmat.primitives import serialization

from app.providers.identity.base import (
    IdentityProviderUnavailableError,
    TokenInvalidError,
)
from app.providers.identity.oidc import OIDCVerifier
from tests.jwt_support import (
    AUDIENCE,
    DISCOVERY_URL,
    ISSUER,
    JWKS_URL,
    SigningKey,
    discovery,
    jwks,
    make_token,
)
from tests.support import make_settings

pytestmark = pytest.mark.unit


@pytest.fixture
def key() -> SigningKey:
    return SigningKey()


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


def verifier(http: httpx.AsyncClient, **overrides: object) -> OIDCVerifier:
    values: dict[str, object] = {
        "oidc_issuer": ISSUER,
        "oidc_audience": AUDIENCE,
        "oidc_jwks_min_refresh_seconds": 0,
        **overrides,
    }
    return OIDCVerifier(make_settings(**values), http)


@respx.mock
async def test_valid_token_is_accepted(http: httpx.AsyncClient, key: SigningKey) -> None:
    respx.get(DISCOVERY_URL).respond(json=discovery())
    respx.get(JWKS_URL).respond(json=jwks(key))

    result = await verifier(http).verify(make_token(key, sub="alice"))

    assert result.issuer == ISSUER
    assert result.subject == "alice"
    assert result.email == "alice@example.test"


@respx.mock
async def test_audience_list_containing_ours_is_accepted(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    respx.get(DISCOVERY_URL).respond(json=discovery())
    respx.get(JWKS_URL).respond(json=jwks(key))

    token = make_token(key, audience=["account", AUDIENCE])

    assert (await verifier(http).verify(token)).subject == "user-123"


@respx.mock
@pytest.mark.parametrize(
    "token_kwargs",
    [
        pytest.param({"expires_in": -120}, id="expired"),
        pytest.param({"audience": "someone-else"}, id="wrong-audience"),
        pytest.param({"issuer": "https://evil.test/realms/knowledgeos"}, id="wrong-issuer"),
        pytest.param({"issued_offset": 3600}, id="issued-in-the-future"),
        pytest.param({"sub": ""}, id="empty-subject"),
    ],
)
async def test_claim_violations_are_rejected(
    http: httpx.AsyncClient, key: SigningKey, token_kwargs: dict[str, object]
) -> None:
    respx.get(DISCOVERY_URL).respond(json=discovery())
    respx.get(JWKS_URL).respond(json=jwks(key))

    with pytest.raises(TokenInvalidError):
        await verifier(http).verify(make_token(key, **token_kwargs))  # type: ignore[arg-type]


@respx.mock
async def test_signature_from_another_key_is_rejected(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    attacker = SigningKey(kid=key.kid)  # same kid, different private key
    respx.get(DISCOVERY_URL).respond(json=discovery())
    respx.get(JWKS_URL).respond(json=jwks(key))

    with pytest.raises(TokenInvalidError):
        await verifier(http).verify(make_token(attacker))


def _b64(data: dict[str, object]) -> str:
    return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()


@respx.mock
async def test_alg_none_is_rejected(http: httpx.AsyncClient, key: SigningKey) -> None:
    respx.get(DISCOVERY_URL).respond(json=discovery())
    respx.get(JWKS_URL).respond(json=jwks(key))
    header = _b64({"alg": "none", "kid": key.kid, "typ": "JWT"})
    payload = _b64({"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "exp": 9999999999, "iat": 1})

    with pytest.raises(TokenInvalidError):
        await verifier(http).verify(f"{header}.{payload}.")


@respx.mock
async def test_hmac_with_public_key_as_secret_is_rejected(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    """Algorithm confusion: HS256 signed with the published public key must never verify."""
    respx.get(DISCOVERY_URL).respond(json=discovery())
    respx.get(JWKS_URL).respond(json=jwks(key))
    # PyJWT refuses to build this forgery, so assemble it by hand like an attacker would.
    public_pem = key.private.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    signing_input = (
        _b64({"alg": "HS256", "kid": key.kid, "typ": "JWT"})
        + "."
        + _b64({"iss": ISSUER, "aud": AUDIENCE, "sub": "x", "exp": 9999999999, "iat": 1})
    )
    signature = hmac.new(public_pem, signing_input.encode(), hashlib.sha256).digest()
    forged = signing_input + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()

    with pytest.raises(TokenInvalidError):
        await verifier(http).verify(forged)


@respx.mock
async def test_malformed_token_is_rejected(http: httpx.AsyncClient) -> None:
    with pytest.raises(TokenInvalidError):
        await verifier(http).verify("not-a-jwt")


@respx.mock
async def test_unknown_kid_triggers_one_refresh_then_rejects(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    respx.get(DISCOVERY_URL).respond(json=discovery())
    jwks_route = respx.get(JWKS_URL).respond(json=jwks(key))
    v = verifier(http)
    await v.verify(make_token(key))  # warm the cache

    with pytest.raises(TokenInvalidError, match="unknown signing key"):
        await v.verify(make_token(key, kid="rotated-away"))
    assert jwks_route.call_count == 2  # initial load + one refresh


@respx.mock
async def test_key_rotation_is_picked_up_without_restart(http: httpx.AsyncClient) -> None:
    old, new = SigningKey(), SigningKey()
    respx.get(DISCOVERY_URL).respond(json=discovery())
    jwks_route = respx.get(JWKS_URL)
    jwks_route.side_effect = [
        httpx.Response(200, json=jwks(old)),
        httpx.Response(200, json=jwks(old, new)),
    ]
    v = verifier(http)
    await v.verify(make_token(old))

    assert (await v.verify(make_token(new, sub="after-rotation"))).subject == "after-rotation"


@respx.mock
async def test_unknown_kid_refresh_is_rate_limited(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    respx.get(DISCOVERY_URL).respond(json=discovery())
    jwks_route = respx.get(JWKS_URL).respond(json=jwks(key))
    v = verifier(http, oidc_jwks_min_refresh_seconds=3600)
    await v.verify(make_token(key))

    for _ in range(5):
        with pytest.raises(TokenInvalidError):
            await v.verify(make_token(key, kid="bogus"))
    assert jwks_route.call_count == 1  # a flood of bogus kids can't hammer the IdP


@respx.mock
async def test_idp_unreachable_without_cached_keys_is_unavailable(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    respx.get(DISCOVERY_URL).mock(side_effect=httpx.ConnectError("down"))

    with pytest.raises(IdentityProviderUnavailableError):
        await verifier(http).verify(make_token(key))


@respx.mock
async def test_cached_keys_survive_idp_outage(http: httpx.AsyncClient, key: SigningKey) -> None:
    respx.get(DISCOVERY_URL).respond(json=discovery())
    jwks_route = respx.get(JWKS_URL)
    jwks_route.side_effect = [httpx.Response(200, json=jwks(key)), httpx.ConnectError("down")]
    v = verifier(http, oidc_jwks_cache_seconds=30)
    await v.verify(make_token(key))
    v._fetched_at -= 3600  # simulate cache expiry

    assert (await v.verify(make_token(key, sub="still-ok"))).subject == "still-ok"


@respx.mock
async def test_discovery_issuer_mismatch_is_unavailable(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    respx.get(DISCOVERY_URL).respond(json={"issuer": "https://evil.test", "jwks_uri": JWKS_URL})

    with pytest.raises(IdentityProviderUnavailableError):
        await verifier(http).verify(make_token(key))


def test_symmetric_algorithms_cannot_be_configured() -> None:
    with pytest.raises(ValueError, match="asymmetric"):
        OIDCVerifier(make_settings(oidc_algorithms=("RS256", "HS256")), httpx.AsyncClient())
