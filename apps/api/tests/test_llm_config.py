import pytest

from app.providers.llm.config import load_config

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("name", "url"),
    [
        ("ollama", "http://ollama:11434/v1"),
        ("groq", "https://api.groq.com/openai/v1"),
        ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/"),
        ("openrouter", "https://openrouter.ai/api/v1"),
    ],
)
async def test_presets_require_explicit_models_keys_and_real_account_limits(
    name: str, url: str
) -> None:
    prefix = name.upper()
    env = {
        f"{prefix}_MODEL": "configured-model",
        f"{prefix}_API_KEY": "secret-value",
        f"{prefix}_RPM": "10",
        f"{prefix}_TPM": "10000",
        f"{prefix}_RPD": "100",
    }
    config = load_config(name, env)
    assert config.base_url == url
    assert config.model_id == "configured-model"
    assert config.is_external == (name != "ollama")
    assert "secret-value" not in repr(config)
    client = config.build()
    assert client.model_id == "configured-model"
    await client.aclose()
    env.pop(f"{prefix}_MODEL")
    with pytest.raises(ValueError, match="model ID"):
        load_config(name, env)


def test_missing_external_key_quotas_and_unsafe_local_routing_are_not_silent_fallbacks() -> None:
    with pytest.raises(ValueError, match="requires a key"):
        load_config("groq", {"GROQ_MODEL": "model"})
    with pytest.raises(ValueError, match="account limits"):
        load_config("ollama", {"OLLAMA_MODEL": "model"})
    with pytest.raises(ValueError, match="remote/cloud"):
        load_config(
            "ollama", {"OLLAMA_MODEL": "model", "OLLAMA_BASE_URL": "https://remote.test/v1"}
        )
    with pytest.raises(ValueError, match="remote/cloud"):
        load_config("ollama", {"OLLAMA_MODEL": "model-cloud"})
