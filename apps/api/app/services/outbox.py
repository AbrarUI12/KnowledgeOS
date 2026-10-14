"""Transactional outbox (ADR-005): events are rows written in the same transaction as the business
change, so they exist if and only if the change commits. The dispatcher (Session 16) publishes
them; consumers must be idempotent.

Every event carries a W3C `traceparent` in its payload so the worker's spans can join the
request's trace once tracing lands (Session 43).
"""

import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import RequestContext
from app.db.base import new_uuid
from app.db.models import OutboxEvent


def new_traceparent() -> str:
    return f"00-{secrets.token_hex(16)}-{secrets.token_hex(8)}-01"


async def emit_system(
    session: AsyncSession,
    organization_id: uuid.UUID,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID | str,
    payload: dict[str, Any] | None = None,
    *,
    available_at: datetime | None = None,
) -> None:
    """Emit an event outside a request (workers, retries). `available_at` delays delivery."""
    event = OutboxEvent(
        id=new_uuid(),
        organization_id=organization_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=str(aggregate_id),
        payload_json={"traceparent": new_traceparent(), **(payload or {})},
    )
    if available_at is not None:
        event.available_at = available_at
    session.add(event)
    await session.flush()


async def emit(
    session: AsyncSession,
    ctx: RequestContext,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID | str,
    payload: dict[str, Any] | None = None,
) -> None:
    await emit_system(
        session, ctx.organization_id, event_type, aggregate_type, aggregate_id, payload
    )
