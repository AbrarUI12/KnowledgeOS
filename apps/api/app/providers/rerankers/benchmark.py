"""CPU measurements on prepared artifacts: python -m app.providers.rerankers.benchmark."""

import argparse
import asyncio
import json
import statistics
import time

from app.providers.rerankers.cross_encoder import CrossEncoderReranker


async def benchmark(model_path: str, onnx_file: str) -> dict[str, object]:
    provider = CrossEncoderReranker(
        model_id=model_path,
        onnx_file=onnx_file,
        timeout_seconds=180,
    )
    query = "How many weeks of paid parental leave do eligible employees receive?"
    passages = [
        "Eligible employees receive sixteen weeks of fully paid parental leave under HR-142-B. "
        "Requests must reach the people team thirty days before the planned start date.",
        "The support runbook describes backups, network configuration and disk capacity. "
        "Contact engineering if the health check fails.",
    ]
    scores = await provider.rerank(query, passages)
    if scores[0] <= scores[1]:
        raise AssertionError("real reranker did not rank the relevant policy first")
    measurements: dict[str, object] = {
        "backend": "onnx",
        "device": "cpu",
        "threads": 2,
        "batch_size": 8,
        "max_length": 512,
        "onnx_file": onnx_file,
        "relevance_scores": scores,
    }
    for size in (20, 30):
        candidates = [passages[index % 2] for index in range(size)]
        samples = []
        for _ in range(3):
            start = time.perf_counter()
            result = await provider.rerank(query, candidates)
            if len(result) != size:
                raise AssertionError("real reranker returned the wrong score count")
            samples.append(round((time.perf_counter() - start) * 1000, 2))
        measurements[str(size)] = {"samples_ms": samples, "median_ms": statistics.median(samples)}
    return measurements


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--onnx-file", default="onnx/model_quint8_avx2.onnx")
    arguments = parser.parse_args()
    print(json.dumps(asyncio.run(benchmark(arguments.model_path, arguments.onnx_file))))


if __name__ == "__main__":
    main()
