"""Pre-download Docling's CPU PDF/OCR model assets for an offline worker image."""

import argparse
from pathlib import Path


def main() -> None:
    from docling.utils.model_downloader import download_models

    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    download_models(
        output_dir=arguments.output_dir,
        with_code_formula=False,
        with_picture_classifier=False,
        with_rapidocr=True,
    )


if __name__ == "__main__":
    main()
