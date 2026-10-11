"""Generate text-based format documents (CSV, HTML, Markdown, TXT) for the demo corpus."""

from __future__ import annotations

import csv
from pathlib import Path


def generate_csv(
    output_path: Path,
    title: str,
    rows: list[list[str]],
) -> None:
    """Generate a CSV file with the given rows."""
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if title:
            writer.writerow([title])
        for row in rows:
            writer.writerow(row)


def generate_txt(
    output_path: Path,
    title: str,
    paragraphs: list[str],
) -> None:
    """Generate a plain text file."""
    with open(output_path, "w", encoding="utf-8") as f:
        if title:
            f.write(f"{title}\n")
            f.write("=" * len(title) + "\n\n")
        for para in paragraphs:
            f.write(f"{para}\n\n")


def generate_html(
    output_path: Path,
    title: str,
    sections: list[dict[str, str | list[str]]],
) -> None:
    """Generate an HTML document."""
    html_parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        f"  <title>{title}</title>",
        "</head>",
        "<body>",
        f"  <h1>{title}</h1>",
    ]

    for section in sections:
        heading = section.get("heading", "")
        content = section.get("content", [])

        if heading:
            html_parts.append(f"  <h2>{heading}</h2>")

        if isinstance(content, list):
            html_parts.append("  <ul>")
            for item in content:
                html_parts.append(f"    <li>{item}</li>")
            html_parts.append("  </ul>")
        elif isinstance(content, str):
            html_parts.append(f"  <p>{content}</p>")

    html_parts.extend(["</body>", "</html>"])

    output_path.write_text("\n".join(html_parts), encoding="utf-8")


def generate_markdown(
    output_path: Path,
    title: str,
    sections: list[dict[str, str | list[str]]],
) -> None:
    """Generate a Markdown document."""
    md_parts = [f"# {title}", ""]

    for section in sections:
        heading = section.get("heading", "")
        content = section.get("content", [])

        if heading:
            md_parts.append(f"## {heading}")
            md_parts.append("")

        if isinstance(content, list):
            for item in content:
                md_parts.append(f"- {item}")
            md_parts.append("")
        elif isinstance(content, str):
            md_parts.append(content)
            md_parts.append("")

    output_path.write_text("\n".join(md_parts), encoding="utf-8")
