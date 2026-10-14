"""Local cross encoder with bounded admission and caller latency, never an implicit fallback.

Python cannot stop native inference in-process. A timed-out inference retains the one global
slot until it actually completes; later callers wait within their deadline and a bounded
coroutine admission capacity, without queuing additional native work/threads.
Model downloads/ONNX exports should be warmed before serving. A stuck native operation requires
process replacement by the supervisor, not unbounded additional inference threads.
"""

import asyncio
import math
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from typing import TYPE_CHECKING, Literal, cast

from app.providers.rerankers.base import RerankerUnavailableError

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder
    from sentence_transformers.base.modality_types import PairInput

_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kos-reranker")
_INFERENCE = Lock()
_WAITERS = BoundedSemaphore(32)
_MODELS: dict[
    tuple[str, str, str, str | None, str | None, str | None, int, int], "CrossEncoder"
] = {}


def _load_model(
    model_id: str,
    device: str,
    backend: Literal["torch", "onnx"],
    revision: str | None,
    cache_folder: str | None,
    onnx_file: str | None,
    max_length: int,
    threads: int,
) -> "CrossEncoder":
    import torch
    from sentence_transformers import CrossEncoder

    torch.set_num_threads(threads)
    kwargs: dict[str, object] = {}
    if backend == "onnx":
        import onnxruntime  # type: ignore[import-untyped]  # upstream lacks stubs

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        kwargs = {"provider": "CPUExecutionProvider", "session_options": options}
        if onnx_file:
            kwargs["file_name"] = onnx_file
            kwargs["export"] = False
    return cast(
        "CrossEncoder",
        CrossEncoder(
            model_id,
            device=device,
            backend=backend,
            revision=revision,
            cache_folder=cache_folder,
            trust_remote_code=False,
            max_length=max_length,
            model_kwargs=kwargs,
        ),
    )


class CrossEncoderReranker:
    is_external = False

    def __init__(
        self,
        *,
        model_id: str = "BAAI/bge-reranker-v2-m3",
        backend: Literal["torch", "onnx"] = "onnx",
        device: Literal["cpu", "cuda"] = "cpu",
        revision: str | None = None,
        cache_folder: str | None = None,
        onnx_file: str | None = None,
        max_length: int = 512,
        batch_size: int = 8,
        threads: int = 2,
        timeout_seconds: float = 5,
        max_candidates: int = 100,
    ) -> None:
        if (
            not model_id
            or min(max_length, batch_size, threads, max_candidates) < 1
            or not math.isfinite(timeout_seconds)
            or timeout_seconds <= 0
        ):
            raise ValueError("reranker requires a model and positive finite limits")
        if backend not in {"torch", "onnx"} or device not in {"cpu", "cuda"}:
            raise ValueError("invalid reranker backend/device")
        if backend == "onnx" and device != "cpu":
            raise ValueError("ONNX reranker is CPU-only; CUDA requires explicit torch backend")
        self.model_id = model_id
        self.backend, self.device = backend, device
        self.revision, self.cache_folder, self.onnx_file = revision, cache_folder, onnx_file
        self.max_length, self.batch_size, self.threads = max_length, batch_size, threads
        self.timeout_seconds, self.max_candidates = timeout_seconds, max_candidates

    def _predict(self, query: str, passages: list[str]) -> list[float]:
        try:
            key = (
                self.model_id,
                self.device,
                self.backend,
                self.revision,
                self.cache_folder,
                self.onnx_file,
                self.max_length,
                self.threads,
            )
            if key not in _MODELS:
                _MODELS[key] = _load_model(
                    self.model_id,
                    self.device,
                    self.backend,
                    self.revision,
                    self.cache_folder,
                    self.onnx_file,
                    self.max_length,
                    self.threads,
                )
            pairs: list[PairInput] = [(query, passage) for passage in passages]
            raw = (
                _MODELS[key]
                .predict(
                    pairs,
                    batch_size=self.batch_size,
                    show_progress_bar=False,
                    convert_to_numpy=True,
                )
                .tolist()
            )
            if (
                not isinstance(raw, list)
                or len(raw) != len(passages)
                or any(
                    isinstance(score, bool)
                    or not isinstance(score, (float, int))
                    or not math.isfinite(score)
                    for score in raw
                )
            ):
                raise RerankerUnavailableError("Reranker returned invalid scores.")
            return [float(score) for score in raw]
        except RerankerUnavailableError:
            raise
        except Exception:
            raise RerankerUnavailableError("The configured reranker is unavailable.") from None
        finally:
            _INFERENCE.release()

    async def rerank(self, query: str, passages: Sequence[str]) -> list[float]:
        if (
            not isinstance(query, str)
            or isinstance(passages, str)
            or any(not isinstance(passage, str) for passage in passages)
            or len(passages) > self.max_candidates
        ):
            raise ValueError("invalid reranker inputs or candidate count")
        if not passages:
            return []
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        if not _WAITERS.acquire(blocking=False):
            raise RerankerUnavailableError("Reranker waiting capacity is full.")
        try:
            # Native completion releases a process-global thread lock, even after the request
            # loop is cancelled/closed. An asyncio semaphore would bind to one event loop and
            # cannot safely serve independent loops; poll this bounded gate without native
            # waiter threads. Only the admitted inference is submitted to the executor.
            while not _INFERENCE.acquire(blocking=False):
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise RerankerUnavailableError("Reranker timed out awaiting a slot.")
                await asyncio.sleep(min(0.01, remaining))
        finally:
            _WAITERS.release()
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            _INFERENCE.release()
            raise RerankerUnavailableError("Reranker timed out awaiting a slot.")
        try:
            future = _EXECUTOR.submit(self._predict, query, list(passages))
        except Exception:
            _INFERENCE.release()
            raise RerankerUnavailableError("Reranker is unavailable.") from None
        try:
            wrapped = asyncio.wrap_future(future)
            wrapped.add_done_callback(lambda done: None if done.cancelled() else done.exception())
            return await asyncio.wait_for(
                asyncio.shield(wrapped),
                timeout=remaining,
            )
        except TimeoutError:
            raise RerankerUnavailableError("Reranker timed out.") from None
