"""Generate DOCX documents using python-docx for the demo corpus."""

from __future__ import annotations

from pathlib import Path

from docx import Document


def generate_docx(
    output_path: Path,
    title: str,
    sections: list[dict[str, str | list[str]]],
) -> None:
    """Generate a DOCX with the given title and sections."""
    doc = Document()

    # Title
    doc.add_heading(title, level=0)

    for section in sections:
        heading = section.get("heading", "")
        content = section.get("content", [])

        if heading:
            doc.add_heading(str(heading), level=1)

        if isinstance(content, list):
            for para_text in content:
                doc.add_paragraph(str(para_text))
        elif isinstance(content, str):
            doc.add_paragraph(content)

    doc.save(str(output_path))
