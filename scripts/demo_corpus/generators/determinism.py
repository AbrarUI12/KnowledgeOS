"""Helpers that make generated OOXML documents byte-for-byte reproducible.

The demo corpus is committed to the repository and consumed by retrieval,
ingestion and evaluation tests. Any run of `make demo-corpus` must therefore
produce files that are identical down to the last byte, on every machine and at
any point in time. Three libraries are used, and each embeds something
non-deterministic unless we normalise it:

* reportlab (PDF): the ``/Info`` ``CreationDate``/``ModDate`` and the document
  ``/ID`` are seeded from the wall clock. ``SimpleDocTemplate(..., invariant=1)``
  makes reportlab emit fixed values instead.
* python-docx / python-pptx (DOCX/PPTX): the core properties we set are honoured,
  but the ZIP container stores each entry's *modification time* from the wall
  clock in the local-file/central-directory headers.
* openpyxl (XLSX): in addition to the ZIP timestamps, openpyxl force-overwrites
  ``docProps/core.xml``'s ``dcterms:modified`` with the current UTC time at save
  time (``openpyxl/writer/excel.py``), so the value we assign to
  ``workbook.properties.modified`` is discarded.

:func:`normalize_ooxml` rewrites a saved DOCX/PPTX/XLSX file in place: it stamps
every ZIP entry with a fixed timestamp, clears the platform/attribute bits and
rewrites any ``dcterms:created``/``dcterms:modified`` in ``docProps/core.xml`` to
the same fixed instant. After that the bytes are stable across runs.
"""

from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path

# One fixed instant shared by every generated document, so the corpus has a
# stable, meaningless "creation" date regardless of when it is regenerated.
FIXED_DATE = datetime(2020, 1, 1, 0, 0, 0)
FIXED_ISO = "2020-01-01T00:00:00Z"
# ZIP timestamps use the DOS epoch (1980-01-01) as their lower bound; any
# in-range fixed tuple works. We reuse the corpus date for consistency.
FIXED_ZIP_DATE = (2020, 1, 1, 0, 0, 0)

CREATOR = "KnowledgeOS Demo Corpus"


def normalize_ooxml(path: Path) -> None:
    """Rewrite ``path`` (a DOCX/PPTX/XLSX file) so its bytes are reproducible.

    Reads every entry of the ZIP container and writes it back with a fixed
    header timestamp and no host-dependent attributes, and pins the core-property
    created/modified timestamps to :data:`FIXED_ISO`. Compression is preserved
    per entry; re-compression uses the deterministic default level.
    """
    with zipfile.ZipFile(path, "r") as zin:
        items: list[tuple[str, bytes, int]] = []
        for info in zin.infolist():
            items.append((info.filename, zin.read(info.filename), info.compress_type))

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, data, compress_type in items:
            if name == "docProps/core.xml":
                data = _pin_core_property_dates(data)
            info = zipfile.ZipInfo(name, date_time=FIXED_ZIP_DATE)
            info.compress_type = compress_type
            # Clear host/OS-dependent metadata so the header bytes are identical
            # regardless of the operating system that produced the file.
            info.external_attr = 0
            info.internal_attr = 0
            info.create_system = 0
            zout.writestr(info, data)


def _pin_core_property_dates(data: bytes) -> bytes:
    """Replace created/modified timestamps in ``docProps/core.xml`` with a fixed value."""
    text = data.decode("utf-8")
    text = re.sub(
        r"(<dcterms:(?:created|modified)[^>]*>)[^<]*(</dcterms:(?:created|modified)>)",
        r"\g<1>" + FIXED_ISO + r"\g<2>",
        text,
    )
    return text.encode("utf-8")
