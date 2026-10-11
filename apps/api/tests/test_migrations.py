import asyncio

import asyncpg
import pytest
from alembic import command

from app.core.config import Settings
from tests.support import alembic_config


def _extensions(settings: Settings) -> set[str]:
    dsn = settings.database_migration_url.get_secret_value().replace("+asyncpg", "")

    async def fetch() -> set[str]:
        conn = await asyncpg.connect(dsn)
        try:
            return {r["extname"] for r in await conn.fetch("SELECT extname FROM pg_extension")}
        finally:
            await conn.close()

    return asyncio.run(fetch())


@pytest.mark.integration
def test_migrations_upgrade_downgrade_upgrade(integration_settings: Settings) -> None:
    cfg = alembic_config(integration_settings)

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    assert {"vector", "pg_trgm"} <= _extensions(integration_settings)
