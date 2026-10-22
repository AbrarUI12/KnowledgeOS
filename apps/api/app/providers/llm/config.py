"""Explicit provider configuration; no client/global environment mutation or model defaults.

External account quotas MUST be configured from the account's actual free-tier limits, not
assumed from a changing public table. This module neither discovers keys nor calls endpoints.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from app.providers.llm.openai_compatible import OpenAICompatibleLLM
from app.rag.generation.throttle import ProviderLimits

_ENDPOINTS = {
    "ollama": "http://ollama:11434/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "openrouter": "https://openrouter.ai/api/v1",
}


@dataclass(frozen=True)
class LLMConfig:
    provider_id: str
    model_id: str
    base_url: str
    is_external: bool
    limits: ProviderLimits
    quota_group: str
    api_key: str | None = field(default=None, repr=False)

    def build(self) -> OpenAICompatibleLLM:
        return OpenAICompatibleLLM(
            base_url=self.base_url,
            provider_id=self.provider_id,
            model_id=self.model_id,
            is_external=self.is_external,
            api_key=self.api_key,
        )


def load_config(name: str, environ: Mapping[str, str]) -> LLMConfig:
    if name not in _ENDPOINTS:
        raise ValueError("unknown generation provider")
    prefix = name.upper()
    model = environ.get(f"{prefix}_MODEL", "").strip()
    if not model or len(model) > 256:
        raise ValueError("an explicit generation model ID is required")
    url = environ.get(f"{prefix}_BASE_URL", _ENDPOINTS[name])
    external = name != "ollama"
    if not external and (
        urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1", "ollama"}
        or model.endswith("-cloud")
    ):
        raise ValueError("the local Ollama preset cannot route to a remote/cloud model")
    key = environ.get(f"{prefix}_API_KEY")
    if external and not key:
        raise ValueError("the selected external generation provider requires a key")
    try:
        limits = ProviderLimits(
            *(int(environ[f"{prefix}_{limit}"]) for limit in ("RPM", "TPM", "RPD"))
        )
    except (KeyError, ValueError):
        raise ValueError("configure positive provider RPM/TPM/RPD account limits") from None
    group = environ.get(f"{prefix}_QUOTA_GROUP", name)
    if not group or len(group) > 200:
        raise ValueError("invalid generation quota group")
    return LLMConfig(name, model, url, external, limits, group, key)
