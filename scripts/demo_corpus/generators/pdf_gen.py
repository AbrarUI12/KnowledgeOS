"""Generate PDF documents using reportlab for the demo corpus."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer


def generate_pdf(
    output_path: Path,
    title: str,
    sections: list[dict[str, str | list[str]]],
) -> None:
    """Generate a PDF with the given title and sections.

    Each section is a dict with 'heading' and 'content' (list of paragraphs).
    """
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18,
    )

    styles = getSampleStyleSheet()
    story: list[Paragraph | Spacer | PageBreak] = []

    # Title
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Title"],
        fontSize=20,
        spaceAfter=12,
    )
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 0.5 * inch))

    heading_style = styles["Heading1"]
    body_style = styles["BodyText"]

    for section in sections:
        heading = section.get("heading", "")
        content = section.get("content", [])

        if heading:
            story.append(Paragraph(heading, heading_style))
            story.append(Spacer(1, 6))

        if isinstance(content, list):
            for para_text in content:
                story.append(Paragraph(str(para_text), body_style))
                story.append(Spacer(1, 6))
        elif isinstance(content, str):
            story.append(Paragraph(content, body_style))
            story.append(Spacer(1, 6))

    doc.build(story)
