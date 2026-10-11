"""Test helpers shared by fixtures and tests."""

from pathlib import Path

from alembic.config import Config as AlembicConfig

from app.core.config import Environment, Settings

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]


def make_settings(**overrides: object) -> Settings:
    """Settings for tests. `model_validate` skips env/.env sources, so the developer's local
    configuration can never leak into a test run."""
    values: dict[str, object] = {"environment": Environment.TEST, "log_json": True, **overrides}
    return Settings.model_validate(values)


def alembic_config(settings: Settings) -> AlembicConfig:
    cfg = AlembicConfig(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.attributes["database_url"] = settings.database_migration_url.get_secret_value()
    cfg.attributes["configure_logger"] = False
    return cfg
