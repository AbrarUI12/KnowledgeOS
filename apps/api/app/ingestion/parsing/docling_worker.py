"""Private subprocess entry point. Receives only an internally-created request file."""

import json
import sys
from pathlib import Path


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (request["memory_bytes"], request["memory_bytes"]))
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from app.ingestion.parsing.docling import to_canonical

    # Layout and table models are required even for native text PDFs: the model-free pipeline
    # loses headings, reading order and tables. OCR is added by T3.3.
    options = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
    if request.get("artifacts_path"):
        options.artifacts_path = Path(request["artifacts_path"])
    options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU)
    converter = DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
    )
    result = converter.convert(Path(request["source"]), raises_on_error=True)
    canonical = to_canonical(
        result.document, filename=request["filename"], mime_type=request["mime_type"]
    )
    Path(request["output"]).write_text(canonical.model_dump_json(), encoding="utf-8")


if __name__ == "__main__":
    main()
