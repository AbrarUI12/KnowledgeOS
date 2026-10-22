"""Opaque keyset cursors (plan §26.1): base64 of `(created_at, id)`, stable under inserts.

Keyset pagination never repeats or skips rows that existed when paging started, because each page
continues strictly after the last `(created_at, id)` seen rather than at an offset.
"""

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, tuple_

from app.api.errors import ValidationFailed

MAX_PAGE_SIZE = 100


def encode_cursor(created_at: datetime, row_id: uuid.UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(row_id)]).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        created_at, row_id = json.loads(raw)
        return datetime.fromisoformat(created_at), uuid.UUID(row_id)
    except (binascii.Error, ValueError, TypeError) as exc:
        raise ValidationFailed("The cursor is invalid.") from exc


def after_cursor(
    created_at_col: Any, id_col: Any, cursor: str | None, *, descending: bool = False
) -> ColumnElement[bool] | None:
    """WHERE clause continuing after `cursor` (None for the first page), in either direction."""
    if cursor is None:
        return None
    created_at, row_id = decode_cursor(cursor)
    if descending:
        return tuple_(created_at_col, id_col) < tuple_(created_at, row_id)
    return tuple_(created_at_col, id_col) > tuple_(created_at, row_id)


def page_limit(limit: int) -> int:
    return max(1, min(limit, MAX_PAGE_SIZE))
