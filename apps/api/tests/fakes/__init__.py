"""Minimal fakes for every T1.0 contract, for unit-testing code that *consumes* a contract.

They are deliberately simple and deterministic. Owners of the real implementations may ship richer
fakes next to their providers (e.g. a scripted FakeLLM in T5.2); keep these working regardless,
since other agents' tests depend on them.
"""

from tests.fakes.providers import (
    FakeChunker,
    FakeContentScanner,
    FakeEmbeddingProvider,
    FakeFileValidator,
    FakeIdentityVerifier,
    FakeLLM,
    FakeMalwareScanner,
    FakeObjectStore,
    FakeParser,
    FakeReranker,
    FakeSearchBackend,
    IndexedChunk,
)

__all__ = [
    "FakeChunker",
    "FakeContentScanner",
    "FakeEmbeddingProvider",
    "FakeFileValidator",
    "FakeIdentityVerifier",
    "FakeLLM",
    "FakeMalwareScanner",
    "FakeObjectStore",
    "FakeParser",
    "FakeReranker",
    "FakeSearchBackend",
    "IndexedChunk",
]
