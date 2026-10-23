"""OIDCVerifier: every acceptance and rejection rule from session.md S07 (T1.1)."""

import asyncio
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


NS = "https://knowledgeos.test/"


@respx.mock
async def test_namespaced_profile_claims_fill_missing_standard_ones(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    # Auth0 access tokens: no email/name unless a post-login Action adds them under a namespace.
    respx.get(DISCOVERY_URL).respond(json=discovery())
    respx.get(JWKS_URL).respond(json=jwks(key))
    token = make_token(
        key,
        sub="auth0|bob",
        extra={
            "email": None,
            "name": None,
            f"{NS}email": "bob@acme.test",
            f"{NS}email_verified": True,
            f"{NS}name": "Bob",
        },
    )
    result = await verifier(http, oidc_claim_namespace=NS).verify(token)
    assert (result.email, result.name) == ("bob@acme.test", "Bob")
    assert result.claims["email_verified"] is True


@respx.mock
async def test_standard_claims_win_and_namespace_is_ignored_unless_configured(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    respx.get(DISCOVERY_URL).respond(json=discovery())
    respx.get(JWKS_URL).respond(json=jwks(key))
    extra = {f"{NS}email": "other@acme.test", f"{NS}email_verified": True}
    token = make_token(key, sub="alice", extra=extra)
    with_ns = await verifier(http, oidc_claim_namespace=NS).verify(token)
    assert with_ns.email == "alice@example.test"
    unset = await verifier(http).verify(make_token(key, extra={"email": None, **extra}))
    assert unset.email is None
    assert "email_verified" not in unset.claims


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


@respx.mock
async def test_idp_outage_with_expired_cache_is_rate_limited(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    """Review #13 (HIGH): after a failed expiry refresh, requests keep using the cached keys
    instead of each making a blocking call to the down IdP."""
    respx.get(DISCOVERY_URL).respond(json=discovery())
    jwks_route = respx.get(JWKS_URL)
    jwks_route.side_effect = [httpx.Response(200, json=jwks(key))] + [
        httpx.ConnectError("down")
    ] * 10
    v = verifier(http, oidc_jwks_cache_seconds=30, oidc_jwks_min_refresh_seconds=3600)
    await v.verify(make_token(key))
    v._fetched_at -= 3600  # cache expired, IdP now down

    for i in range(5):
        assert (await v.verify(make_token(key, sub=f"u{i}"))).subject == f"u{i}"
    assert jwks_route.call_count == 2  # initial load + one failed refresh, then backoff


@respx.mock
async def test_idp_outage_without_keys_backs_off(http: httpx.AsyncClient, key: SigningKey) -> None:
    discovery_route = respx.get(DISCOVERY_URL).mock(side_effect=httpx.ConnectError("down"))
    v = verifier(http, oidc_jwks_min_refresh_seconds=3600)

    for _ in range(5):
        with pytest.raises(IdentityProviderUnavailableError):
            await v.verify(make_token(key))
    assert discovery_route.call_count == 1


@respx.mock
@pytest.mark.parametrize(
    ("discovery_body", "jwks_body"),
    [
        pytest.param(["not", "an", "object"], None, id="discovery-list"),
        pytest.param({"issuer": 123, "jwks_uri": JWKS_URL}, None, id="discovery-issuer-type"),
        pytest.param(None, ["not", "an", "object"], id="jwks-list"),
        pytest.param(None, {"keys": "nope"}, id="jwks-keys-type"),
    ],
)
async def test_malformed_idp_documents_are_unavailable_not_500(
    http: httpx.AsyncClient, key: SigningKey, discovery_body: object, jwks_body: object
) -> None:
    """Review #13 (MEDIUM): well-formed JSON of the wrong shape must map to 503, not crash."""
    respx.get(DISCOVERY_URL).respond(
        json=discovery_body if discovery_body is not None else discovery()
    )
    respx.get(JWKS_URL).respond(json=jwks_body if jwks_body is not None else jwks(key))

    with pytest.raises(IdentityProviderUnavailableError):
        await verifier(http).verify(make_token(key))


@respx.mock
async def test_trailing_slash_issuer_is_matched_exactly(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    """Review #13 (HIGH): Auth0-style issuers end in "/"; iss must match exactly, either way."""
    slash_issuer = ISSUER + "/"
    respx.get(DISCOVERY_URL).respond(json={"issuer": slash_issuer, "jwks_uri": JWKS_URL})
    respx.get(JWKS_URL).respond(json=jwks(key))
    v = verifier(http, oidc_issuer=slash_issuer)

    accepted = await v.verify(make_token(key, issuer=slash_issuer))
    assert accepted.issuer == slash_issuer
    with pytest.raises(TokenInvalidError):
        await v.verify(make_token(key, issuer=ISSUER))  # same host, missing slash


@respx.mock
async def test_issuer_without_slash_rejects_slashed_tokens_and_discovery(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    respx.get(DISCOVERY_URL).respond(json=discovery())
    respx.get(JWKS_URL).respond(json=jwks(key))
    with pytest.raises(TokenInvalidError):
        await verifier(http).verify(make_token(key, issuer=ISSUER + "/"))

    respx.get(DISCOVERY_URL).respond(json={"issuer": ISSUER + "/", "jwks_uri": JWKS_URL})
    with pytest.raises(IdentityProviderUnavailableError):
        await verifier(http).verify(make_token(key))


@respx.mock
async def test_concurrent_cold_requests_share_one_jwks_fetch(
    http: httpx.AsyncClient, key: SigningKey
) -> None:
    discovery_route = respx.get(DISCOVERY_URL).respond(json=discovery())
    jwks_route = respx.get(JWKS_URL).respond(json=jwks(key))
    v = verifier(http)

    results = await asyncio.gather(*(v.verify(make_token(key, sub=f"u{i}")) for i in range(10)))

    assert {r.subject for r in results} == {f"u{i}" for i in range(10)}
    assert (discovery_route.call_count, jwks_route.call_count) == (1, 1)


def test_symmetric_algorithms_cannot_be_configured() -> None:
    with pytest.raises(ValueError, match="asymmetric"):
        OIDCVerifier(make_settings(oidc_algorithms=("RS256", "HS256")), httpx.AsyncClient())
