"""Generate XLSX documents using openpyxl for the demo corpus."""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font


def generate_xlsx(
    output_path: Path,
    title: str,
    sheets: list[dict[str, str | list[list[str]]]],
) -> None:
    """Generate an XLSX workbook with the given title and sheets.

    Each sheet is a dict with 'name' and 'rows' (list of lists of strings).
    """
    wb = Workbook()
    # Remove default sheet
    wb.remove(wb.active)

    for sheet_spec in sheets:
        name = str(sheet_spec.get("name", "Sheet1"))
        rows = sheet_spec.get("rows", [])

        ws = wb.create_sheet(title=name)

        if isinstance(rows, list):
            for row_idx, row in enumerate(rows, 1):
                if isinstance(row, list):
                    for col_idx, cell_value in enumerate(row, 1):
                        cell = ws.cell(row=row_idx, column=col_idx, value=str(cell_value))
                        if row_idx == 1:
                            cell.font = Font(bold=True)
                elif isinstance(row, str):
                    ws.cell(row=row_idx, column=1, value=row)

    wb.save(str(output_path))
