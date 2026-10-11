import pytest
from pydantic import SecretStr

from app.core.config import Environment
from app.core.logging import REDACTED, redact_sensitive
from tests.support import make_settings


@pytest.mark.unit
def test_settings_parse_environment_and_secrets() -> None:
    settings = make_settings(environment="staging", redis_url="redis://cache:6379/1")

    assert settings.environment is Environment.STAGING
    assert isinstance(settings.redis_url, SecretStr)
    assert "cache" not in repr(settings.redis_url)  # secrets are masked in reprs
    assert settings.json_logs is True


@pytest.mark.unit
def test_local_environment_defaults_to_console_logs() -> None:
    assert make_settings(environment="local", log_json=None).json_logs is False


@pytest.mark.unit
def test_settings_reject_unknown_environment() -> None:
    with pytest.raises(ValueError, match="environment"):
        make_settings(environment="moon")


@pytest.mark.unit
def test_redaction_scrubs_sensitive_keys_recursively() -> None:
    event = {
        "event": "login",
        "password": "hunter2",
        "headers": {"Authorization": "Bearer abc", "accept": "json"},
        "items": [{"api_key": "k"}, {"name": "ok"}],
        "user": "alice",
    }

    result = redact_sensitive(None, "info", event)

    assert result["password"] == REDACTED
    assert result["headers"] == {"Authorization": REDACTED, "accept": "json"}
    assert result["items"] == [{"api_key": REDACTED}, {"name": "ok"}]
    assert result["user"] == "alice"
    assert result["event"] == "login"
