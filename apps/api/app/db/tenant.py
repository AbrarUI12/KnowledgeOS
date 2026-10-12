"""Transaction-local tenant context for row-level security (plan §8.2, ADR-004).

`set_config(name, value, true)` scopes the value to the current transaction, so it can never leak
to the next user of a pooled connection. Never use session-level `SET` for these.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_SET_CONTEXT = text(
    "SELECT set_config('app.organization_id', :org, true), set_config('app.user_id', :uid, true)"
)


async def set_tenant_context(
    session: AsyncSession, organization_id: uuid.UUID | None, user_id: uuid.UUID | None = None
) -> None:
    """Set (or clear, with None) the RLS context for the session's current transaction."""
    if not session.in_transaction():
        raise RuntimeError("tenant context must be set inside a transaction")
    await session.execute(
        _SET_CONTEXT,
        {
            "org": str(organization_id) if organization_id else "",
            "uid": str(user_id) if user_id else "",
        },
    )


@asynccontextmanager
async def tenant_session(
    sessionmaker: async_sessionmaker[AsyncSession],
    organization_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
) -> AsyncIterator[AsyncSession]:
    """A session in one transaction acting inside `organization_id` (for workers and scripts).

    Commits on success, rolls back on error.
    """
    async with sessionmaker() as session, session.begin():
        await set_tenant_context(session, organization_id, user_id)
        yield session
