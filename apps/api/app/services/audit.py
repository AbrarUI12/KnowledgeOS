"""Audit trail (plan §7.9): one append-only row per administrative change, written in the same
transaction as the change, so a rolled-back change leaves no audit row and vice versa.

Never put secrets, tokens or document content into `metadata`.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.authorization import RequestContext
from app.db.models import AuditEvent


async def record(
    session: AsyncSession,
    ctx: RequestContext,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    session.add(
        AuditEvent(
            organization_id=ctx.organization_id,
            actor_type="user",
            actor_id=ctx.user_id,
            action=action,
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            request_id=ctx.request_id,
            metadata_json=metadata or {},
        )
    )
    await session.flush()
