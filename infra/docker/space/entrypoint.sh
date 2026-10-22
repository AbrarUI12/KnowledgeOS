#!/bin/sh
# Space entrypoint: wait for the database (Neon scales to zero), migrate on staging only
# (production migrations become a separate CD step, S61), then run every process under supervisord.
set -eu

python - <<'PY'
import asyncio
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import Settings


async def wait() -> None:
    # Same URL format as the app (e.g. postgresql+asyncpg://…?ssl=require for Neon).
    engine = create_async_engine(Settings().database_migration_url.get_secret_value())
    try:
        for attempt in range(30):
            try:
                async with engine.connect() as connection:
                    await connection.execute(text("SELECT 1"))
                return
            except Exception as exc:  # report the type only, never the URL
                print(f"database not ready ({type(exc).__name__}), retry {attempt + 1}/30", flush=True)
                await asyncio.sleep(5)
        sys.exit("database unreachable")
    finally:
        await engine.dispose()


asyncio.run(wait())
PY

if [ "${ENVIRONMENT:-}" = "staging" ]; then
  alembic upgrade head
fi

exec supervisord -c /etc/knowledgeos/supervisord.conf
