"""`scripts/get_token.py` (T1.8): the dev-only guard must check the issuer's host exactly."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "get_token.py"


@pytest.fixture(scope="module")
def get_token() -> ModuleType:
    spec = importlib.util.spec_from_file_location("get_token_script", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.unit
@pytest.mark.parametrize(
    ("issuer", "allowed"),
    [
        ("http://localhost:8080/realms/knowledgeos", True),
        ("http://127.0.0.1:8080/realms/knowledgeos", True),
        ("http://[::1]:8080/realms/knowledgeos", True),
        ("http://localhost.evil.com/realms/knowledgeos", False),
        ("https://evil.com/localhost/realms/knowledgeos", False),
        ("https://127.0.0.1.nip.io/realms/knowledgeos", False),
        ("https://knowledgeos.us.auth0.com/", False),
        ("not a url", False),
    ],
)
def test_only_loopback_issuers_are_allowed(
    get_token: ModuleType, issuer: str, allowed: bool
) -> None:
    assert get_token.is_local_issuer(issuer) is allowed


@pytest.mark.unit
def test_token_summary_decodes_claims(get_token: ModuleType) -> None:
    import base64
    import json

    payload = base64.urlsafe_b64encode(
        json.dumps({"aud": "knowledgeos-api", "sub": "abcdef123456", "exp": 1}).encode()
    ).rstrip(b"=")
    summary = get_token._decode_token_summary(["h", payload.decode(), "s"], "alice@acme.test")
    assert summary == "Token for alice@acme.test (aud=knowledgeos-api, sub=abcdef12..., exp=1)"
