import asyncio
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pytest

from app.providers.rerankers import cross_encoder as local
from app.providers.rerankers.base import RerankerProvider, RerankerUnavailableError

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

pytestmark = pytest.mark.unit


class EncoderDependency:
    def __init__(self) -> None:
        self.calls: list[tuple[list[tuple[str, str]], dict[str, Any]]] = []
        self.started, self.release = Event(), Event()
        self.release.set()
        self.output: list[float] | None = None

    def predict(self, pairs: list[tuple[str, str]], **kwargs: Any) -> np.ndarray[Any, Any]:
        self.calls.append((pairs, kwargs))
        self.started.set()
        assert self.release.wait(2)
        return np.array(self.output if self.output is not None else list(range(len(pairs))))


@pytest.fixture
def encoder(monkeypatch: pytest.MonkeyPatch) -> tuple[EncoderDependency, list[tuple[object, ...]]]:
    dependency, loads = EncoderDependency(), []
    monkeypatch.setattr(local, "_MODELS", {})

    def load(*args: object) -> "CrossEncoder":
        loads.append(args)
        return cast("CrossEncoder", dependency)

    monkeypatch.setattr(local, "_load_model", load)
    return dependency, loads


async def test_lazy_cached_encoder_scores_preserve_input_order(
    encoder: tuple[EncoderDependency, list[tuple[object, ...]]],
) -> None:
    dependency, loads = encoder
    provider = local.CrossEncoderReranker(model_id="fixture", batch_size=2)
    assert isinstance(provider, RerankerProvider)
    assert not provider.is_external
    assert not loads
    assert await provider.rerank("query", ["first", "second"]) == [0, 1]
    assert await local.CrossEncoderReranker(model_id="fixture").rerank("q", ["one"]) == [0]
    assert len(loads) == 1
    assert loads[0][2] == "onnx"
    assert loads[0][-2:] == (512, 2)
    assert dependency.calls[0][0] == [("query", "first"), ("query", "second")]
    assert dependency.calls[0][1]["batch_size"] == 2
    assert await provider.rerank("query", []) == []


async def test_timeout_keeps_bounded_slot_until_native_work_finishes(
    encoder: tuple[EncoderDependency, list[tuple[object, ...]]],
) -> None:
    dependency, _ = encoder
    dependency.release.clear()
    provider = local.CrossEncoderReranker(model_id="fixture", timeout_seconds=0.02)
    try:
        with pytest.raises(RerankerUnavailableError, match="timed out"):
            await provider.rerank("q", ["passage"])
        assert dependency.started.is_set()
        for _ in range(10):
            with pytest.raises(RerankerUnavailableError, match="timed out awaiting a slot"):
                await provider.rerank("q", ["passage"])
        assert len(dependency.calls) == 1
    finally:
        dependency.release.set()
        await asyncio.wait_for(asyncio.wrap_future(local._EXECUTOR.submit(lambda: None)), 2)
    assert await provider.rerank("q", ["passage"]) == [0]


async def test_two_overlapping_requests_wait_without_queuing_native_work(
    encoder: tuple[EncoderDependency, list[tuple[object, ...]]],
) -> None:
    dependency, _ = encoder
    dependency.release.clear()
    provider = local.CrossEncoderReranker(model_id="fixture", timeout_seconds=1)
    first = asyncio.create_task(provider.rerank("q", ["first"]))
    assert await asyncio.to_thread(dependency.started.wait, 1)
    second = asyncio.create_task(provider.rerank("q", ["second"]))
    try:
        await asyncio.sleep(0.02)
        assert len(dependency.calls) == 1
        assert not second.done()
    finally:
        dependency.release.set()
    first_result, second_result = await asyncio.gather(first, second)
    assert first_result == [0]
    assert second_result == [0]
    assert len(dependency.calls) == 2


async def test_cancelling_a_waiter_never_submits_work_or_leaks_the_slot(
    encoder: tuple[EncoderDependency, list[tuple[object, ...]]],
) -> None:
    dependency, _ = encoder
    dependency.release.clear()
    provider = local.CrossEncoderReranker(model_id="fixture", timeout_seconds=1)
    first = asyncio.create_task(provider.rerank("q", ["first"]))
    assert await asyncio.to_thread(dependency.started.wait, 1)
    waiting = asyncio.create_task(provider.rerank("q", ["cancelled"]))
    await asyncio.sleep(0.02)
    waiting.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await waiting
        assert len(dependency.calls) == 1
    finally:
        dependency.release.set()
    assert await first == [0]
    assert await provider.rerank("q", ["third"]) == [0]
    assert [call[0][0][1] for call in dependency.calls] == ["first", "third"]


@pytest.mark.parametrize("scores", [[float("nan")], [float("inf")], [0, 1]])
async def test_invalid_scores_fail_without_model_substitution(
    scores: list[float],
    encoder: tuple[EncoderDependency, list[tuple[object, ...]]],
) -> None:
    dependency, loads = encoder
    dependency.output = scores
    with pytest.raises(RerankerUnavailableError, match="invalid scores"):
        await local.CrossEncoderReranker(model_id="fixture").rerank("q", ["passage"])
    assert len(loads) == 1
    assert loads[0][0] == "fixture"


async def test_model_load_failure_does_not_echo_private_text_or_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(local, "_MODELS", {})

    def unavailable(*args: object) -> "CrossEncoder":
        raise RuntimeError("private document text")

    monkeypatch.setattr(local, "_load_model", unavailable)
    with pytest.raises(RerankerUnavailableError) as error:
        await local.CrossEncoderReranker().rerank(
            "private document text", ["private document text"]
        )
    assert "private" not in str(error.value)
    assert not local._INFERENCE.locked()


def test_configuration_cannot_silently_choose_a_different_backend() -> None:
    with pytest.raises(ValueError, match="CPU-only"):
        local.CrossEncoderReranker(device="cuda")
    with pytest.raises(ValueError, match="finite"):
        local.CrossEncoderReranker(timeout_seconds=float("nan"))


def test_preparation_refuses_to_overwrite_existing_artifacts(tmp_path: Path) -> None:
    from app.providers.rerankers.prepare import prepare_model

    artifact = tmp_path / "model.onnx"
    artifact.write_bytes(b"existing model artifact")
    with pytest.raises(ValueError, match="must be empty"):
        prepare_model(model_id="BAAI/bge-reranker-v2-m3", cache_folder=None, output=tmp_path)
    assert artifact.read_bytes() == b"existing model artifact"
