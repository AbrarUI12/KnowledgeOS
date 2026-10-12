"""Test helpers shared by fixtures and tests."""

from pathlib import Path

from alembic.config import Config as AlembicConfig
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from app.core.config import Environment, Settings

API_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = API_DIR.parents[1]


class _IsolatedSettings(Settings):
    """Settings built only from explicit values: no environment variables, no `.env` file."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


def make_settings(**overrides: object) -> Settings:
    """Settings for tests. The developer's environment and `.env` can never leak into a test run
    (a plain `Settings.model_validate` still reads them)."""
    values: dict[str, object] = {"environment": Environment.TEST, "log_json": True, **overrides}
    return _IsolatedSettings(**values)  # type: ignore[arg-type]


def alembic_config(settings: Settings) -> AlembicConfig:
    cfg = AlembicConfig(str(API_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(API_DIR / "migrations"))
    cfg.attributes["database_url"] = settings.database_migration_url.get_secret_value()
    cfg.attributes["configure_logger"] = False
    return cfg
