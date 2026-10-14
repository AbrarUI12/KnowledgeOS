"""Populate a Hugging Face model cache for offline embedding workers (T4.1)."""

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3-Embedding-0.6B")
    parser.add_argument("--revision", default="main")
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    snapshot_download(
        repo_id=arguments.model,
        revision=arguments.revision,
        cache_dir=arguments.output_dir,
        allow_patterns=["*.json", "*.txt", "*.model", "*.safetensors"],
    )


if __name__ == "__main__":
    main()
