"""Process-wide model providers for the query path (T5.3): the reranker and the context token
counter. Each is built once per configuration; a provider that can't load is None, and the
pipeline then degrades explicitly (fused order, flagged) when the RAG profile allows it."""

from collections.abc import Callable
from functools import lru_cache

import structlog

from app.core.config import Settings
from app.providers.rerankers.base import RerankerProvider

logger = structlog.get_logger(__name__)
TokenCounter = Callable[[str], int]


@lru_cache(maxsize=4)
def _reranker(
    model: str,
    backend: str,
    onnx_file: str | None,
    cache_folder: str | None,
    timeout: float,
) -> RerankerProvider | None:
    try:
        from app.providers.rerankers import CrossEncoderReranker

        return CrossEncoderReranker(
            model_id=model,
            backend=backend,  # type: ignore[arg-type]  # validated by Settings
            onnx_file=onnx_file,
            cache_folder=cache_folder,
            timeout_seconds=timeout,
        )
    except Exception as exc:  # missing extras or bad configuration: degrade, never substitute
        logger.warning("reranker_unavailable", error_type=type(exc).__name__)
        return None


def reranker_provider(settings: Settings) -> RerankerProvider | None:
    """The configured local cross-encoder (weights load lazily on the first call)."""
    return _reranker(
        settings.reranker_model,
        settings.reranker_backend,
        settings.reranker_onnx_file,
        settings.reranker_cache_folder,
        settings.reranker_timeout_seconds,
    )


@lru_cache(maxsize=2)
def _model_tokenizer(model: str) -> TokenCounter:
    from app.ingestion.chunking.tokenizer import ModelTokenizer

    return ModelTokenizer(model).count


def context_token_counter(settings: Settings) -> TokenCounter:
    """Counts context tokens with the embedding model's tokenizer, a close and conservative
    stand-in until the generation gateway (T5.2) exposes the generation model's own; the packer
    budget leaves headroom for the rest of the prompt anyway."""
    return _model_tokenizer(settings.embedding_model)
