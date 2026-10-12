"""`Idempotency-Key` support for important POSTs (plan §26.1).

Flow inside the request transaction:
1. `begin` inserts a placeholder row for (user, key) *before* doing the work. A concurrent request
   with the same key blocks on the unique index until the first one commits, then sees the row.
2. If a completed row already exists: same request fingerprint → replay the stored response;
   different fingerprint → 409 `idempotency_key_reused`.
3. `complete` stores the response; it commits atomically with the work. A failed request rolls
   back its placeholder, so the key can be retried.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import IdempotencyKeyReused
from app.db.base import new_uuid
from app.db.models import IdempotencyKey


@dataclass(frozen=True, slots=True)
class StoredResponse:
    status_code: int
    body: Any


def fingerprint(method: str, path: str, body: Any) -> str:
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{method} {path}\n{canonical}".encode()).hexdigest()


async def begin(
    session: AsyncSession, *, user_id: uuid.UUID, key: str, request_fingerprint: str, ttl: timedelta
) -> StoredResponse | None:
    """Claim the key, or return the stored response to replay."""
    now = datetime.now(UTC)
    await session.execute(
        delete(IdempotencyKey).where(
            IdempotencyKey.user_id == user_id,
            IdempotencyKey.key == key,
            IdempotencyKey.expires_at < now,
        )
    )
    claimed = await session.scalar(
        insert(IdempotencyKey)
        .values(
            id=new_uuid(),
            user_id=user_id,
            key=key,
            request_fingerprint=request_fingerprint,
            expires_at=now + ttl,
        )
        .on_conflict_do_nothing(index_elements=[IdempotencyKey.user_id, IdempotencyKey.key])
        .returning(IdempotencyKey.id)
    )
    if claimed is not None:
        return None

    existing = (
        await session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id, IdempotencyKey.key == key
            )
        )
    ).scalar_one()
    if existing.request_fingerprint != request_fingerprint or existing.status_code is None:
        raise IdempotencyKeyReused
    return StoredResponse(existing.status_code, existing.response_json)


async def complete(
    session: AsyncSession, *, user_id: uuid.UUID, key: str, status_code: int, body: Any
) -> None:
    await session.execute(
        update(IdempotencyKey)
        .where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
        .values(status_code=status_code, response_json=body)
    )
