"""Transactional outbox (ADR-005): events are rows written in the same transaction as the business
change, so they exist if and only if the change commits. The dispatcher (Session 16) publishes
them; consumers must be idempotent."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import RequestContext
from app.db.base import new_uuid
from app.db.models import OutboxEvent


async def emit(
    session: AsyncSession,
    ctx: RequestContext,
    event_type: str,
    aggregate_type: str,
    aggregate_id: uuid.UUID | str,
    payload: dict[str, Any] | None = None,
) -> None:
    session.add(
        OutboxEvent(
            id=new_uuid(),
            organization_id=ctx.organization_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=str(aggregate_id),
            payload_json=payload or {},
        )
    )
    await session.flush()
