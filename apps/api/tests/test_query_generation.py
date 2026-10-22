"""Query-path generation wiring (T5.3): sanitizer, extractive fake, policy-bound generator, scope
filters and evidence status. No Docker, no network."""

import uuid
from typing import Any, cast

import pytest
from redis.asyncio import Redis

from app.api.errors import ServiceUnavailable
from app.domain.enums import EvidenceStatus
from app.domain.schemas.retrieval import QueryRequest
from app.providers.llm.base import ChatMessage, Role
from app.rag.generation.gateway import LLMGateway
from app.rag.generation.grounded import GroundedAnswer
from app.rag.generation.prompt import load_prompt, messages_for
from app.rag.orchestration.generation import (
    ExtractiveFakeLLM,
    PolicyView,
    build_generator,
    sanitize_answer,
)
from app.services.query import _filters, evidence_status
from tests.support import make_settings
from tests.test_citation_validator import item

pytestmark = pytest.mark.unit
REDIS = cast(Redis, object())  # never used: build_generator only stores it in the throttle
GROQ = {
    "GROQ_API_KEY": "test-key-not-real",
    "GROQ_MODEL": "llama-test",
    "GROQ_RPM": "30",
    "GROQ_TPM": "6000",
    "GROQ_RPD": "1000",
}
OLLAMA = {
    "OLLAMA_BASE_URL": "http://localhost:11434/v1",
    "OLLAMA_MODEL": "qwen3:8b",
    "OLLAMA_RPM": "60",
    "OLLAMA_TPM": "60000",
    "OLLAMA_RPD": "10000",
}


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Sixteen weeks [S1].", "Sixteen weeks [S1]."),
        ("Weeks [S1, S3]. ![x](https://evil.example/?d=1)", "Weeks [S1, S3]. [x]"),
        ("See [the policy](https://evil.example) [S2].", "See [the policy] [S2]."),
        ("Ref [S1].\n\n[1]: https://evil.example/track", "Ref [S1].\n\n"),
        ("<img src=https://evil.example/p.png>Weeks [S1].", "Weeks [S1]."),
        ("Visit <https://example.com> [S1].", "Visit https://example.com [S1]."),
    ],
)
def test_sanitizer_removes_everything_a_renderer_could_fetch(raw: str, clean: str) -> None:
    assert sanitize_answer(raw) == clean


async def test_extractive_fake_cites_the_first_source_or_abstains() -> None:
    evidence = [item("S1")]
    messages = messages_for("How long?", evidence, load_prompt())

    answer = await ExtractiveFakeLLM().generate(messages)
    empty = await ExtractiveFakeLLM().generate(
        [ChatMessage(role=Role.USER, content="Question: anything")]
    )

    assert answer.text == "Eligible employees receive sixteen weeks of leave. [S1]"
    assert empty.text == "INSUFFICIENT_EVIDENCE"


def test_generation_needs_configuration() -> None:
    with pytest.raises(ServiceUnavailable):
        build_generator(make_settings(), REDIS, PolicyView(), len)


def test_external_models_need_explicit_permission_and_local_only_policies_block_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name, value in {**GROQ, **OLLAMA}.items():
        monkeypatch.setenv(name, value)
    groq = make_settings(llm_provider="groq")
    allowed = make_settings(llm_provider="groq", llm_allow_external=True)
    with_fallback = make_settings(
        llm_provider="groq", llm_fallback_providers="ollama", llm_allow_external=True
    )

    with pytest.raises(ServiceUnavailable):  # external, but LLM_ALLOW_EXTERNAL is off
        build_generator(groq, REDIS, PolicyView(), len)
    gateway = build_generator(allowed, REDIS, PolicyView(), len).provider
    assert isinstance(gateway, LLMGateway)
    assert gateway.is_external
    with pytest.raises(ServiceUnavailable):  # a local-only KB never reaches Groq
        build_generator(allowed, REDIS, PolicyView(local_only=True), len)
    local = build_generator(with_fallback, REDIS, PolicyView(local_only=True), len).provider
    assert (local.provider_id, local.model_id, local.is_external) == ("ollama", "qwen3:8b", False)
    pinned = build_generator(
        with_fallback, REDIS, PolicyView(generation_models=("qwen3:8b",)), len
    ).provider
    assert pinned.provider_id == "ollama"


def test_fake_generation_is_refused_outside_local_and_test() -> None:
    with pytest.raises(ValueError, match="local development and tests only"):
        make_settings(llm_provider="fake", environment="staging")


def test_document_scope_narrows_filters_and_never_widens_them() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()

    def filters(scope: list[uuid.UUID], ids: list[uuid.UUID]) -> object:
        return _filters(
            QueryRequest.model_validate(
                {
                    "question": "q",
                    "scope": {"document_ids": scope},
                    "filters": {"document_ids": ids},
                }
            )
        )

    assert filters([], []).document_ids == ()  # type: ignore[attr-defined]
    assert filters([a], []).document_ids == (a,)  # type: ignore[attr-defined]
    assert filters([a, b], [b]).document_ids == (b,)  # type: ignore[attr-defined]
    assert filters([a], [b]) is None  # disjoint: nothing to search, not "no filter"


def test_evidence_status_follows_explicit_rules() -> None:
    answered = GroundedAnswer(text="x [S1]")
    assert evidence_status(answered, []) is EvidenceStatus.STRONG
    assert evidence_status(answered, ["rerank_bypassed"]) is EvidenceStatus.PARTIAL
    assert evidence_status(answered, ["dense_unavailable"]) is EvidenceStatus.RETRIEVAL_DEGRADED
    abstained = GroundedAnswer(text="no", abstained=True)
    assert evidence_status(abstained, ["dense_unavailable"]) is EvidenceStatus.INSUFFICIENT


async def test_closing_the_stream_cancels_generation_and_records_a_cancelled_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    import time

    from app.providers.llm.base import GenerationParams
    from app.rag.orchestration.generation import Generator, message_counter
    from app.rag.orchestration.profiles import ActiveProfile, RagProfileConfig
    from app.services import query

    started, cancelled = asyncio.Event(), asyncio.Event()

    class Slow(ExtractiveFakeLLM):
        async def generate(self, messages, params=None):  # type: ignore[no-untyped-def]
            started.set()
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                cancelled.set()
                raise

    statuses: list[str] = []

    async def persist(sessionmaker, p, *, status, **_):  # type: ignore[no-untyped-def]
        statuses.append(status)

    monkeypatch.setattr(query, "_persist", persist)
    prepared = query.Prepared(
        run_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        question="How long?",
        profile=ActiveProfile(uuid.uuid4(), "default-hybrid", 1, RagProfileConfig()),
        generator=Generator(Slow(), message_counter(len), GenerationParams(), 6000),
        evidence=(item("S1"),),
        candidates=1,
        degraded=[],
        retrieval_ms=1.0,
        rerank_ms=None,
        started=time.perf_counter(),
    )
    stream = query.events(prepared, cast(Any, None))
    names = []
    async for name, _ in stream:
        names.append(name)
        if name == "stage" and names.count("stage") == 3:  # generation.started
            break
    # The client disconnects while the model is generating: the server cancels the stream task.
    pending = asyncio.ensure_future(anext(stream))
    await asyncio.wait_for(started.wait(), 5)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending

    await asyncio.wait_for(cancelled.wait(), 5)  # the model call was cancelled too
    assert names == ["meta", "stage", "stage", "sources", "stage"]
    assert statuses == ["cancelled"]
