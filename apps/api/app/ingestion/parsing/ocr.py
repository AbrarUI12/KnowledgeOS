"""CPU Docling OCR adapter for scans and standalone images, with confidence provenance."""

from pathlib import Path

from docling.datamodel.document import ConversionResult

from app.ingestion.canonical import BlockType, CanonicalDocument
from app.ingestion.parsing.docling import IMAGE_FORMATS, DoclingParser


class OcrParser(DoclingParser):
    def __init__(
        self,
        *,
        timeout_seconds: float = 120,
        memory_bytes: int = 4 * 1024**3,
        artifacts_path: Path | None = None,
        max_input_bytes: int = 50 * 1024**2,
        max_pages: int = 500,
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds,
            memory_bytes=memory_bytes,
            artifacts_path=artifacts_path,
            max_input_bytes=max_input_bytes,
            max_pages=max_pages,
            ocr=True,
        )

    def supports(self, mime_type: str) -> bool:
        return mime_type == "application/pdf" or mime_type in IMAGE_FORMATS


def add_ocr_provenance(document: CanonicalDocument, result: ConversionResult) -> None:
    for block in document.blocks:
        confidences: list[float] = []
        for box in block.bbox:
            page = next((page for page in result.pages if page.page_no == box.page), None)
            if page is None or page.size is None:
                continue
            for cell in page.cells:
                if not cell.from_ocr:
                    continue
                bounds = cell.rect.to_bounding_box().to_top_left_origin(page.size.height)
                overlap = max(0, min(box.x1, bounds.r) - max(box.x0, bounds.l)) * max(
                    0, min(box.y1, bounds.b) - max(box.y0, bounds.t)
                )
                if overlap > 0:
                    confidences.append(float(cell.confidence))
        if confidences:
            block.ocr_confidence = round(sum(confidences) / len(confidences), 6)
            block.extra["ocr"] = True
            if block.type is BlockType.PARAGRAPH:
                block.type = BlockType.IMAGE_TEXT
            if block.ocr_confidence < 0.8 and "low_ocr_confidence" not in document.warnings:
                document.warnings.append("low_ocr_confidence")
