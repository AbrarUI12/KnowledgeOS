import asyncio
import json
import math
import time
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
import respx

from app.providers.embeddings import (
    FakeEmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    SentenceTransformersEmbeddingProvider,
)
from app.providers.embeddings import sentence_transformers as local
from app.providers.embeddings.base import EmbeddingProvider, EmbeddingUnavailableError
from app.providers.embeddings.validation import EmbeddingDimensionError, vectors

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer

pytestmark = pytest.mark.unit


async def test_fake_contract_determinism_normalization_and_empty_batches() -> None:
    provider = FakeEmbeddingProvider()
    assert isinstance(provider, EmbeddingProvider)
    assert not provider.is_external
    first = await provider.embed_documents(["parental leave policy", "", "policy"])
    assert first == await provider.embed_documents(["parental leave policy", "", "policy"])
    assert await provider.embed_query("policy") == first[2]
    assert await provider.embed_documents([]) == []
    assert all(len(vector) == 1024 and math.hypot(*vector) == pytest.approx(1) for vector in first)


@pytest.mark.parametrize(
    "raw",
    [[[float("nan"), 1]], [[float("inf"), 1]], [[0, 0]], [[True, 1]], [["1", 2]], [[10**500, 1]]],
)
def test_invalid_numerical_output_fails_closed(raw: object) -> None:
    with pytest.raises(EmbeddingUnavailableError):
        vectors(raw, count=1, dimension=2, normalized=True)


def test_dimension_mismatch_is_not_truncated_or_padded() -> None:
    with pytest.raises(EmbeddingDimensionError, match="Expected dimension 1024, received 2"):
        vectors([[1, 2]], count=1, dimension=1024, normalized=True)


@respx.mock
async def test_http_order_batching_model_prompt_and_normalization() -> None:
    def response(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "configured-model"
        assert body["encoding_format"] == "float"
        assert body["dimensions"] == 2
        assert request.headers["Authorization"] == "Bearer test-key"
        return httpx.Response(
            200,
            json={
                "model": "configured-model",
                "data": [
                    {
                        "index": index,
                        "embedding": [3, 4]
                        if body["input"][index].startswith("Query:")
                        else ([1, 0] if index == 0 else [0, 1]),
                    }
                    for index in reversed(range(len(body["input"])))
                ],
            },
        )

    route = respx.post("http://embeddings.test/v1/embeddings").mock(side_effect=response)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://embeddings.test/v1",
        model_id="configured-model",
        is_external=False,
        dimension=2,
        max_batch=2,
        api_key="test-key",
        send_dimensions=True,
        query_prompt="Query: ",
    )
    assert isinstance(provider, EmbeddingProvider)
    try:
        values = await provider.embed_documents(["a", "b", "c"])
        assert route.call_count == 2
        assert values == [[1, 0], [0, 1], [1, 0]]
        assert await provider.embed_query("policy") == pytest.approx([0.6, 0.8])
        assert json.loads(route.calls[-1].request.content)["input"] == ["Query: policy"]
        assert await provider.embed_documents([]) == []
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "payload",
    [
        {"model": "wrong", "data": [{"index": 0, "embedding": [1, 0]}]},
        {"data": [{"index": 0, "embedding": [1, 0]}]},
        {"model": "model", "data": []},
        {"model": "model", "data": [{"index": -1, "embedding": [1, 0]}]},
        {"model": "model", "data": [{"index": True, "embedding": [1, 0]}]},
        {"model": "model", "data": [{"index": 0, "embedding": "base64"}]},
    ],
)
@respx.mock
async def test_http_malformed_or_substituted_output_is_rejected(payload: object) -> None:
    respx.post("http://embeddings.test/v1/embeddings").respond(200, json=payload)
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://embeddings.test/v1", model_id="model", dimension=2, is_external=True
    )
    try:
        with pytest.raises(EmbeddingUnavailableError):
            await provider.embed_query("private document text")
    finally:
        await provider.aclose()


@respx.mock
async def test_http_failure_and_response_limit_never_echo_text_or_fallback() -> None:
    route = respx.post("http://embeddings.test/v1/embeddings").respond(
        503, text="private document text"
    )
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://embeddings.test/v1",
        model_id="model",
        is_external=True,
        max_response_bytes=20,
    )
    try:
        with pytest.raises(EmbeddingUnavailableError) as error:
            await provider.embed_query("private document text")
        assert "private" not in str(error.value)
        assert route.call_count == 1
        route.respond(200, content=b"x" * 100)
        with pytest.raises(EmbeddingUnavailableError, match="exceeds"):
            await provider.embed_query("policy")
    finally:
        await provider.aclose()


class ArrayResult:
    def __init__(self, count: int) -> None:
        self.count = count

    def tolist(self) -> list[list[float]]:
        return [[3.0, 4.0, 0.0, 0.0] for _ in range(self.count)]


class EncoderDependency:
    """Controlled model dependency; the provider's batching/guards/locks remain real."""

    def __init__(self) -> None:
        self.prompts = {"query": "instruction"}
        self.calls: list[dict[str, Any]] = []
        self.active = self.peak = 0

    def get_sentence_embedding_dimension(self) -> int:
        return 4

    def encode(self, texts: list[str], **kwargs: Any) -> ArrayResult:
        self.active += 1
        self.peak = max(self.peak, self.active)
        self.calls.append({"texts": list(texts), **kwargs})
        time.sleep(0.01)
        self.active -= 1
        return ArrayResult(len(texts))


@pytest.fixture
def encoder(monkeypatch: pytest.MonkeyPatch) -> tuple[EncoderDependency, list[tuple[object, ...]]]:
    dependency, loads = EncoderDependency(), []
    monkeypatch.setattr(local, "_MODELS", {})

    def load(*args: object) -> local.ModelEntry:
        loads.append(args)
        return local.ModelEntry(cast("SentenceTransformer", dependency))

    monkeypatch.setattr(local, "_load_model", load)
    return dependency, loads


async def test_local_lazy_singleton_prompts_batching_and_serialized_inference(
    encoder: tuple[EncoderDependency, list[tuple[object, ...]]],
) -> None:
    dependency, loads = encoder
    a = SentenceTransformersEmbeddingProvider(
        model_id="fixture", dimension=4, max_batch=2, device="cpu"
    )
    b = SentenceTransformersEmbeddingProvider(
        model_id="fixture", dimension=4, max_batch=2, device="cpu"
    )
    assert isinstance(a, EmbeddingProvider)
    assert not loads
    output, query = await asyncio.gather(
        a.embed_documents(["a", "b", "c"]), b.embed_query("policy")
    )
    assert len(loads) == 1
    assert dependency.peak == 1
    assert len(output) == 3
    assert query == pytest.approx([0.6, 0.8, 0, 0])
    document_calls = [call for call in dependency.calls if call["prompt_name"] is None]
    assert [len(call["texts"]) for call in document_calls] == [2, 1]
    assert all(call["prompt"] == "" and call["normalize_embeddings"] for call in document_calls)
    assert any(call["prompt_name"] == "query" for call in dependency.calls)


async def test_local_dimension_prompt_and_load_errors_do_not_substitute_models(
    encoder: tuple[EncoderDependency, list[tuple[object, ...]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    dependency, _ = encoder
    bad = SentenceTransformersEmbeddingProvider(model_id="fixture", dimension=1024, device="cpu")
    with pytest.raises(EmbeddingDimensionError):
        await bad.embed_query("policy")
    dependency.prompts = {}
    correct = SentenceTransformersEmbeddingProvider(model_id="fixture", dimension=4, device="cpu")
    with pytest.raises(EmbeddingUnavailableError, match="prompt"):
        await correct.embed_query("policy")

    def unavailable(*args: object) -> local.ModelEntry:
        raise RuntimeError("private document text")

    monkeypatch.setattr(local, "_load_model", unavailable)
    provider = SentenceTransformersEmbeddingProvider(model_id="unavailable", device="cpu")
    with pytest.raises(EmbeddingUnavailableError) as error:
        await provider.embed_query("private document text")
    assert "private" not in str(error.value)


def test_configuration_and_input_guards() -> None:
    with pytest.raises(ValueError, match="positive"):
        FakeEmbeddingProvider(dimension=0)
    with pytest.raises(ValueError, match="positive"):
        SentenceTransformersEmbeddingProvider(max_batch=0)
    with pytest.raises(ValueError, match="endpoint"):
        OpenAICompatibleEmbeddingProvider(
            base_url="file:///tmp/model", model_id="model", is_external=False
        )
