"""Private subprocess entry point. Receives only an internally-created request file."""

import json
import sys
from pathlib import Path


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (request["memory_bytes"], request["memory_bytes"]))
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    from app.ingestion.parsing.docling import to_canonical
    from app.ingestion.parsing.html import clean_html
    from app.ingestion.parsing.ocr import add_ocr_provenance

    # Layout and table models are required even for native text PDFs: the model-free pipeline
    # loses headings, reading order and tables. OCR is added by T3.3.
    options = PdfPipelineOptions(
        do_ocr=request["ocr"],
        do_table_structure=True,
        generate_parsed_pages=request["ocr"],
        ocr_options=RapidOcrOptions(backend="onnxruntime"),
    )
    if request.get("artifacts_path"):
        options.artifacts_path = Path(request["artifacts_path"])
    options.accelerator_options = AcceleratorOptions(device=AcceleratorDevice.CPU, num_threads=2)
    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                backend=PyPdfiumDocumentBackend, pipeline_options=options
            ),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=options),
        }
    )
    source = Path(request["source"])
    metadata: dict[str, str] = {}
    if request["mime_type"] == "text/html":
        cleaned, metadata = clean_html(source.read_bytes())
        source.write_bytes(cleaned)
    result = converter.convert(source, raises_on_error=True, max_num_pages=request["max_pages"])
    canonical = to_canonical(
        result.document, filename=request["filename"], mime_type=request["mime_type"]
    )
    canonical.metadata.update(metadata)
    if metadata.get("html_title"):
        canonical.title = metadata["html_title"]
    if request["ocr"]:
        add_ocr_provenance(canonical, result)
    Path(request["output"]).write_text(canonical.model_dump_json(), encoding="utf-8")


if __name__ == "__main__":
    main()
