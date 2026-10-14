"""Embedding implementations; importing this module does not load model weights."""

from app.providers.embeddings.fake import FakeEmbeddingProvider
from app.providers.embeddings.openai_compatible import OpenAICompatibleEmbeddingProvider
from app.providers.embeddings.sentence_transformers import SentenceTransformersEmbeddingProvider

__all__ = [
    "FakeEmbeddingProvider",
    "OpenAICompatibleEmbeddingProvider",
    "SentenceTransformersEmbeddingProvider",
]
