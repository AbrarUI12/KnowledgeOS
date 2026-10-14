"""Real model check isolated so weights do not remain resident during ingestion tests."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.slow
def test_real_qwen_embeddings_have_1024_normalized_dimensions() -> None:
    cache = Path(".venv/embedding-assets")
    script = """
import asyncio, json, math, sys
from app.providers.embeddings import SentenceTransformersEmbeddingProvider
async def check():
    provider = SentenceTransformersEmbeddingProvider(
        device='cpu', max_seq_length=128,
        cache_folder=sys.argv[1] or None,
    )
    documents = await provider.embed_documents(['Parental leave is sixteen weeks.'])
    query = await provider.embed_query('How long is parental leave?')
    print(json.dumps({'model': provider.model_id,
        'dimensions': [len(documents[0]), len(query)],
        'norms': [math.hypot(*documents[0]), math.hypot(*query)]}))
asyncio.run(check())
"""
    result = subprocess.run(  # noqa: S603 - fixed interpreter and repository-owned script
        [sys.executable, "-c", script, str(cache.resolve()) if cache.exists() else ""],
        capture_output=True,
        text=True,
        timeout=300,
        check=True,
    )
    output = json.loads(result.stdout.splitlines()[-1])
    assert output["model"] == "Qwen/Qwen3-Embedding-0.6B"
    assert output["dimensions"] == [1024, 1024]
    assert output["norms"] == pytest.approx([1, 1])
