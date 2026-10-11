"""Application settings, loaded from environment variables (and the repo-root `.env` locally)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


def _local_env_files() -> tuple[Path, ...]:
    """The repo-root `.env` in a source checkout (marked by docker-compose.yml); none in images."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "docker-compose.yml").is_file():
            return (parent / ".env",)
    return ()


class Environment(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_local_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.LOCAL
    app_name: str = "KnowledgeOS API"
    log_level: str = "INFO"
    log_json: bool | None = Field(
        default=None, description="JSON logs; defaults to on everywhere except local"
    )

    # Runtime role (RLS applies) and migration role (schema owner).
    database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://knowledgeos_app:app_dev_password@localhost:5433/knowledgeos"
    )
    database_migration_url: SecretStr = SecretStr(
        "postgresql+asyncpg://knowledgeos_owner:owner_dev_password@localhost:5433/knowledgeos"
    )
    database_pool_size: int = 5
    database_max_overflow: int = 5

    redis_url: SecretStr = SecretStr("redis://localhost:6380/0")

    s3_endpoint_url: str | None = "http://localhost:9000"
    s3_public_endpoint_url: str | None = "http://localhost:9000"
    s3_region: str = "us-east-1"
    s3_access_key_id: SecretStr = SecretStr("kos_minio")
    s3_secret_access_key: SecretStr = SecretStr("kos_minio_dev_secret")
    s3_force_path_style: bool = True
    s3_bucket_quarantine: str = "kos-quarantine"
    s3_bucket_trusted: str = "kos-trusted"
    s3_bucket_artifacts: str = "kos-artifacts"

    readiness_timeout_seconds: float = 2.0

    @property
    def json_logs(self) -> bool:
        if self.log_json is not None:
            return self.log_json
        return self.environment is not Environment.LOCAL

    @property
    def s3_buckets(self) -> tuple[str, str, str]:
        return (self.s3_bucket_quarantine, self.s3_bucket_trusted, self.s3_bucket_artifacts)


@lru_cache
def get_settings() -> Settings:
    return Settings()
