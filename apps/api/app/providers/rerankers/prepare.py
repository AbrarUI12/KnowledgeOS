"""Explicit offline asset preparation: python -m app.providers.rerankers.prepare.

Use an empty output directory; never overwrite an existing model artifact. Export/quantization
is a deployment preparation step, not an implicit fallback on a serving request.
"""

import argparse
from pathlib import Path


def prepare_model(*, model_id: str, cache_folder: str | None, output: Path) -> None:
    import torch
    from sentence_transformers import CrossEncoder, export_dynamic_quantized_onnx_model

    if output.exists() and any(output.iterdir()):
        raise ValueError("model output directory must be empty")
    torch.set_num_threads(2)
    model = CrossEncoder(
        model_id,
        backend="onnx",
        device="cpu",
        cache_folder=cache_folder,
        trust_remote_code=False,
        max_length=512,
        model_kwargs={"provider": "CPUExecutionProvider"},
    )
    model.save_pretrained(str(output))
    export_dynamic_quantized_onnx_model(
        model,
        quantization_config="avx2",
        model_name_or_path=str(output),
        push_to_hub=False,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--cache-folder")
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    prepare_model(
        model_id=arguments.model, cache_folder=arguments.cache_folder, output=arguments.output
    )


if __name__ == "__main__":
    main()
