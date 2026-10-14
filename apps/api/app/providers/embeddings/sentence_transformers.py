"""Lazy process-wide local encoder; serialized inference, explicit model, bounded sequences."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from threading import RLock
from typing import TYPE_CHECKING, Literal

from app.providers.embeddings.base import EmbeddingUnavailableError
from app.providers.embeddings.validation import EmbeddingDimensionError, texts_list, vectors

if TYPE_CHECKING:
    from sentence_transformers import SentenceTransformer


@dataclass
class ModelEntry:
    model: "SentenceTransformer"
    lock: RLock = field(default_factory=RLock)


_MODELS: dict[tuple[str, str, str | None, str | None, int, int], ModelEntry] = {}
_LOAD_LOCK = RLock()


def _load_model(
    model_id: str,
    device: str,
    revision: str | None,
    cache_folder: str | None,
    max_seq_length: int,
    threads: int,
) -> ModelEntry:
    import torch
    from sentence_transformers import SentenceTransformer

    torch.set_num_threads(threads)
    model = SentenceTransformer(
        model_id,
        device=device,
        revision=revision,
        cache_folder=cache_folder,
        trust_remote_code=False,
        model_kwargs={"dtype": torch.float16 if device == "cuda" else torch.float32},
    )
    model.max_seq_length = max_seq_length
    return ModelEntry(model)


class SentenceTransformersEmbeddingProvider:
    provider_id = "sentence-transformers"
    normalized = True
    is_external = False

    def __init__(
        self,
        *,
        model_id: str = "Qwen/Qwen3-Embedding-0.6B",
        dimension: int = 1024,
        max_batch: int = 8,
        max_seq_length: int = 2048,
        threads: int = 2,
        device: Literal["auto", "cpu", "cuda"] = "auto",
        revision: str | None = None,
        cache_folder: str | None = None,
        query_prompt: str | None = None,
    ) -> None:
        if not model_id or min(dimension, max_batch, max_seq_length, threads) < 1:
            raise ValueError("embedding model and positive limits are required")
        self._model_id, self._dimension, self._max_batch = model_id, dimension, max_batch
        self._max_seq_length, self._threads, self._device = max_seq_length, threads, device
        self.revision, self._cache_folder, self._query_prompt = revision, cache_folder, query_prompt

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_batch(self) -> int:
        return self._max_batch

    def _entry(self) -> ModelEntry:
        import torch

        device = self._device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise EmbeddingUnavailableError("The configured CUDA device is unavailable.")
        key = (
            self.model_id,
            device,
            self.revision,
            self._cache_folder,
            self._max_seq_length,
            self._threads,
        )
        with _LOAD_LOCK:
            if key not in _MODELS:
                _MODELS[key] = _load_model(*key)
            return _MODELS[key]

    def _encode(self, texts: list[str], *, query: bool) -> list[list[float]]:
        try:
            entry = self._entry()
            with entry.lock:
                native_dimension = entry.model.get_sentence_embedding_dimension()
                if native_dimension != self.dimension:
                    raise EmbeddingDimensionError(
                        f"Expected dimension {self.dimension}, model advertises {native_dimension}."
                    )
                prompt_name = "query" if query and self._query_prompt is None else None
                if prompt_name and prompt_name not in entry.model.prompts:
                    raise EmbeddingUnavailableError("The configured query prompt is missing.")
                output = entry.model.encode(
                    texts,
                    batch_size=self.max_batch,
                    prompt_name=prompt_name,
                    prompt=self._query_prompt if query else "",
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
                return vectors(
                    output.tolist(), count=len(texts), dimension=self.dimension, normalized=True
                )
        except (EmbeddingDimensionError, EmbeddingUnavailableError):
            raise
        except Exception:
            raise EmbeddingUnavailableError(
                "The configured local embedding model is unavailable."
            ) from None

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = texts_list(texts)
        result: list[list[float]] = []
        for start in range(0, len(inputs), self.max_batch):
            result.extend(
                await asyncio.to_thread(
                    self._encode, inputs[start : start + self.max_batch], query=False
                )
            )
        return result

    async def embed_query(self, text: str) -> list[float]:
        return (await asyncio.to_thread(self._encode, texts_list([text]), query=True))[0]

    async def warm_up(self) -> None:
        await self.embed_query("warmup")
