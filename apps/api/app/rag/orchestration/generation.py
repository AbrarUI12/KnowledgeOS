"""Generation for the query path (T5.3): T5.2's policy-bound gateway built from settings, the
KB's model policy, and the server-side answer sanitizer.

- Providers come only from configuration (`LLM_PROVIDER`, `LLM_FALLBACK_PROVIDERS`, and each
  provider's own `<PROVIDER>_*` variables); there is no implicit default model and no fallback the
  model policy doesn't allow. External providers also need `LLM_ALLOW_EXTERNAL=true`, and a KB or
  organization policy with `local_only` keeps evidence inside the deployment.
- `LLM_PROVIDER=fake` answers deterministically from the first source (local development and the
  web app's tests); staging and production refuse it (Settings).
- `sanitize_answer` runs on every validated answer: retrieved text is untrusted, so a persuaded
  model must not be able to plant links or images that leak data when an answer is rendered.
"""

import json
import os
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from functools import lru_cache

from dotenv import dotenv_values
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ServiceUnavailable
from app.core.config import Environment, Settings, _local_env_files
from app.db.models import KnowledgeBase, ModelPolicy
from app.providers.llm.base import ChatMessage, GenerationParams, LLMChunk, LLMProvider, LLMResult
from app.providers.llm.config import LLMConfig, load_config
from app.providers.llm.openai_compatible import OpenAICompatibleLLM
from app.providers.llm.validation import estimated_usage, validate_request
from app.rag.generation.gateway import GenerationPolicy, LLMGateway, ProviderTarget
from app.rag.generation.prompt import MessageTokenCounter
from app.rag.generation.throttle import RedisProviderThrottle

TokenCounter = Callable[[str], int]


@dataclass(frozen=True, slots=True)
class PolicyView:
    """The model policy that applies to one KB: its own row, else the organization's."""

    local_only: bool = False
    generation_models: tuple[str, ...] = ()
    # The highest document classification an external model may see (plan §25.2).
    max_external_classification: str = "internal"


@dataclass(frozen=True, slots=True)
class Generator:
    """Everything the pipeline needs to generate one grounded answer."""

    provider: LLMProvider
    count_tokens: MessageTokenCounter
    params: GenerationParams
    max_input_tokens: int


async def model_policy(session: AsyncSession, kb: KnowledgeBase) -> PolicyView:
    rows = list(
        await session.scalars(
            select(ModelPolicy).where(
                ModelPolicy.organization_id == kb.organization_id,
                (ModelPolicy.knowledge_base_id == kb.id) | ModelPolicy.knowledge_base_id.is_(None),
            )
        )
    )
    row = next((r for r in rows if r.knowledge_base_id == kb.id), None) or next(iter(rows), None)
    if row is None:
        return PolicyView()
    return PolicyView(
        row.local_only, tuple(row.generation_models or ()), row.max_external_classification
    )


def message_counter(count: TokenCounter) -> MessageTokenCounter:
    """Prompt size with a per-message allowance for the chat template."""
    return lambda messages: sum(count(m.content) + 8 for m in messages) + 8


def _provider_environ(settings: Settings) -> dict[str, str]:
    environ: dict[str, str] = {}
    if settings.environment is Environment.LOCAL:  # deployed images get real environment only
        for path in _local_env_files():
            if path.is_file():
                environ |= {k: v for k, v in dotenv_values(path).items() if v is not None}
    return environ | dict(os.environ)


@lru_cache(maxsize=8)
def _provider(config: LLMConfig) -> OpenAICompatibleLLM:
    return config.build()  # one HTTP client per configured endpoint for the process


def build_generator(
    settings: Settings, redis: Redis, policy: PolicyView, count_tokens: TokenCounter
) -> Generator:
    """The generator for one request, or 503 when generation isn't configured or the policy
    allows none of the configured models."""
    params = GenerationParams(
        max_output_tokens=settings.llm_max_output_tokens,
        temperature=settings.llm_temperature,
        timeout_seconds=settings.llm_timeout_seconds,
    )
    counter = message_counter(count_tokens)
    if settings.llm_provider is None:
        raise ServiceUnavailable("Answer generation isn't configured.")
    if settings.llm_provider == "fake":
        return Generator(ExtractiveFakeLLM(), counter, params, settings.llm_max_input_tokens)
    environ = _provider_environ(settings)
    names = list(dict.fromkeys([settings.llm_provider, *settings.llm_fallback_list]))
    try:
        configs = [load_config(name, environ) for name in names]
    except ValueError as exc:
        raise ServiceUnavailable(f"Answer generation is misconfigured: {exc}.") from None
    allowed = frozenset(
        (c.provider_id, c.model_id)
        for c in configs
        if not policy.generation_models or c.model_id in policy.generation_models
    )
    gate = GenerationPolicy(
        allowed_models=allowed,
        allow_external=settings.llm_allow_external and not policy.local_only,
        local_only=policy.local_only,
    )
    targets = [
        ProviderTarget(_provider(c), c.quota_group, c.limits, counter)
        for c in configs
        if gate.permits(_provider(c))
    ]
    if not targets:
        raise ServiceUnavailable("No generation model is allowed for this knowledge base.")
    gateway = LLMGateway(
        primary=targets[0],
        fallbacks=targets[1:4],
        policy=gate,
        throttle=RedisProviderThrottle(redis),
    )
    return Generator(gateway, counter, params, settings.llm_max_input_tokens)


# --------------------------------------------------------------------------- sanitizer

_LINK_TARGET = re.compile(r"\]\([^)]*\)")  # [text](url) and ![alt](url): drop the target
_REFERENCE = re.compile(r"^[ \t]{0,3}\[[^\]\n]+\]:[ \t]*\S.*$", re.MULTILINE)
_AUTOLINK = re.compile(r"<((?:https?|mailto|ftp):[^>\s]*)>", re.IGNORECASE)
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_IMAGE_BANG = re.compile(r"!\[")


def sanitize_answer(text: str) -> str:
    """Plain Markdown without links, images, reference definitions or raw HTML. Citation markers
    (`[S1]`, `[S1, S3]`) and the words of a link stay; only what a renderer could fetch or follow
    goes. URLs remain visible as inert text."""
    text = _REFERENCE.sub("", text)
    text = _LINK_TARGET.sub("]", text)
    text = _AUTOLINK.sub(r"\1", text)
    text = _HTML_TAG.sub("", text)
    return _IMAGE_BANG.sub("[", text)


# --------------------------------------------------------------------------- fake

_EVIDENCE = re.compile(
    r'<untrusted_evidence id="(S[1-9][0-9]*)">\n(.*?)\n</untrusted_evidence>', re.S
)
_SENTENCE = re.compile(r"(.+?[.!?])(?:\s|$)", re.S)


class ExtractiveFakeLLM:
    """Deterministic stand-in for local development and tests: answers with the first sentence
    of the first source, cited, or abstains when the prompt carries no evidence."""

    provider_id = "fake"
    model_id = "extractive-v1"
    is_external = False

    def _answer(self, messages: Sequence[ChatMessage]) -> str:
        found = _EVIDENCE.search(messages[-1].content if messages else "")
        if not found:
            return "INSUFFICIENT_EVIDENCE"
        alias, view = found.groups()
        content = " ".join(str(json.loads(view)[0]["content"]).split())
        sentence = _SENTENCE.match(content)
        return f"{(sentence.group(1) if sentence else content)[:400]} [{alias}]"

    async def generate(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> LLMResult:
        params = params or GenerationParams()
        validate_request(messages, params)
        text = self._answer(messages)
        return LLMResult(
            text=text,
            model=self.model_id,
            provider=self.provider_id,
            finish_reason="stop",
            usage=estimated_usage(messages, text),
        )

    async def stream(
        self, messages: Sequence[ChatMessage], params: GenerationParams | None = None
    ) -> AsyncIterator[LLMChunk]:
        result = await self.generate(messages, params)
        yield LLMChunk(delta=result.text)
        yield LLMChunk(finish_reason=result.finish_reason, usage=result.usage)
