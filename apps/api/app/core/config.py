"""Application settings, loaded from environment variables (and the repo-root `.env` locally)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
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


def _malware_scan_required(data: dict[str, Any]) -> bool:
    return data.get("environment") in {Environment.STAGING, Environment.PRODUCTION}


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
    # Outbox dispatcher (S16): its own least-privilege role, see migration 0006.
    dispatcher_database_url: SecretStr = SecretStr(
        "postgresql+asyncpg://knowledgeos_dispatcher:dispatcher_dev_password"
        "@localhost:5433/knowledgeos"
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
    # Explicit timeouts/retries for every storage call (plan §34.1).
    s3_connect_timeout_seconds: float = 5.0
    s3_read_timeout_seconds: float = 30.0
    s3_max_attempts: int = 3  # total attempts including the first

    # "clamav" (default; the `full` Compose profile runs clamd) or "none" for the `core` profile.
    # Staging/production require a real scan regardless (require_malware_scan).
    malware_scanner: Literal["clamav", "none"] = "clamav"
    clamav_host: str = "localhost"
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 30.0
    clamav_max_stream_bytes: int = 50 * 1024 * 1024
    require_malware_scan: bool = Field(default_factory=_malware_scan_required)

    # OIDC (Keycloak locally, Auth0 deployed). Only tokens whose `iss` equals oidc_issuer and whose
    # `aud` contains oidc_audience are accepted (ADR-003).
    oidc_issuer: str = "http://localhost:8080/realms/knowledgeos"
    oidc_audience: str = "knowledgeos-api"
    oidc_jwks_url: str | None = Field(
        default=None, description="Override; normally taken from the issuer's discovery document"
    )
    oidc_algorithms: tuple[str, ...] = ("RS256", "ES256")
    oidc_leeway_seconds: int = Field(default=30, ge=0, le=60)
    oidc_jwks_cache_seconds: int = Field(default=600, ge=30)
    oidc_jwks_min_refresh_seconds: int = Field(
        default=30, ge=0, description="Rate limit for JWKS refreshes triggered by unknown key IDs"
    )
    oidc_http_timeout_seconds: float = 5.0
    user_last_seen_write_interval_seconds: int = 300

    # Organizations (T1.3)
    web_base_url: str = Field(
        default="http://localhost:3000", description="Public web app URL, for invitation links"
    )
    invitation_ttl_hours: int = Field(default=168, ge=1, le=24 * 30)
    idempotency_ttl_hours: int = Field(default=24, ge=1, le=24 * 7)

    # Background work (T3.1)
    celery_broker_url: SecretStr | None = Field(
        default=None, description="Defaults to REDIS_URL when unset"
    )
    ingestion_lease_seconds: int = Field(default=300, ge=10)
    ingestion_max_attempts: int = Field(default=5, ge=1, le=20)
    dispatcher_batch_size: int = Field(default=100, ge=1, le=1000)
    dispatcher_poll_seconds: float = Field(default=1.0, gt=0)
    # Reconciliation sweeper (T3.6)
    reconcile_interval_seconds: int = Field(default=120, ge=10)
    reconcile_stale_seconds: int = Field(default=600, ge=30)
    approval_reminder_seconds: int = Field(default=86_400, ge=60)
    # Local/test only: sleep in every ingestion stage so crash tests can kill a worker mid-stage.
    ingestion_debug_stage_delay_seconds: float = Field(default=0.0, ge=0, le=60)
    # Local/test only: run parsing → chunking with the T1.0 contract fakes from `tests/fakes`
    # (the crash demo mounts them), so the full pipeline persists chunks before every real
    # library has merged. Refused in any other environment.
    ingestion_contract_fakes: bool = False

    # Embeddings (T4.1 providers, T4.2 stage; plan §13, D-004). New KBs record these on their
    # index generation; a provider whose model or dimension differs from its generation's is
    # refused, never substituted (§25.2). The stage registry maps them onto the providers'
    # keyword constructors (`app.ingestion.stages._embedder_kwargs`).
    embedding_provider: Literal["sentence_transformers", "openai_compatible"] = (
        "sentence_transformers"
    )
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_dimension: int = Field(default=1024, ge=1)
    embedding_batch_size: int = Field(default=16, ge=1, le=512)
    embedding_device: Literal["cpu", "cuda", "auto"] = "cpu"
    embedding_base_url: str | None = None  # openai_compatible endpoint (TEI, Infinity, Ollama)
    embedding_api_key: SecretStr | None = None
    embedding_is_external: bool = False  # True if text leaves the deployment (model policy)

    # Reranking (T5.1 provider, T5.3 pipeline; plan §19). A local int8 ONNX cross-encoder; the
    # artifact comes from `python -m app.providers.rerankers.prepare` (offline preparation).
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_backend: Literal["onnx", "torch"] = "onnx"
    reranker_onnx_file: str | None = None  # e.g. onnx/model_quint8_avx2.onnx
    reranker_cache_folder: str | None = None
    reranker_timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    # Search (T4.6). Query runs always store a hash of the normalized query; its text only when
    # retention allows (plan §7.8). Off by default: privacy first.
    retain_query_text: bool = False
    search_max_candidates: int = Field(default=50, ge=1, le=500)

    # Grounded generation (T5.2 gateway, T5.3 pipeline; plan §16, §25.2). Each provider's model,
    # key and account limits come from its own `<PROVIDER>_*` variables (providers/llm/config.py).
    # None = answers unavailable (503); `fake` = deterministic extractive answers, local/test only.
    llm_provider: Literal["ollama", "groq", "gemini", "openrouter", "fake"] | None = None
    llm_fallback_providers: str = ""  # comma-separated, tried in order, only if policy allows
    llm_allow_external: bool = False  # evidence may leave the deployment (Groq/Gemini/OpenRouter)
    llm_max_input_tokens: int = Field(default=6000, ge=512, le=128_000)
    llm_max_output_tokens: int = Field(default=700, ge=16, le=8192)
    llm_temperature: float = Field(default=0.1, ge=0, le=2)
    llm_timeout_seconds: float = Field(default=60.0, gt=0, le=600)

    # Uploads (T2.4)
    upload_max_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    upload_url_ttl_seconds: int = Field(default=900, ge=60, le=3600)

    readiness_timeout_seconds: float = 2.0

    # Browser origins allowed to call the API (CORS). Comma-separated, exact origins only: the
    # web app sends a bearer token, never cookies, so credentials stay disabled (ADR-003).
    web_origins: str = "http://localhost:3000,http://localhost:3100,http://localhost:3200"

    @property
    def web_origin_list(self) -> list[str]:
        """Exact origins (scheme://host[:port]); anything else fails fast at startup."""
        origins = [o.strip() for o in self.web_origins.split(",") if o.strip()]
        for origin in origins:
            parts = urlsplit(origin)
            if (
                "*" in origin
                or parts.scheme not in {"http", "https"}
                or not parts.hostname
                or parts.username is not None
                or parts.password is not None
                or parts.path not in {"", "/"}
                or parts.query
                or parts.fragment
            ):
                raise ValueError(f"WEB_ORIGINS entries must be exact http(s) origins: {origin!r}")
        return [o.rstrip("/") for o in origins]

    @model_validator(mode="after")
    def _embedding_endpoint(self) -> "Settings":
        # Fail at startup, not in every ingestion job, when the endpoint provider has no URL.
        # chunks.embedding is vector(1024) (migration 0010); other sizes need a new index schema.
        if self.embedding_dimension != 1024:
            raise ValueError("EMBEDDING_DIMENSION must be 1024 (chunks.embedding is vector(1024))")
        if self.embedding_provider == "openai_compatible" and not self.embedding_base_url:
            raise ValueError(
                "EMBEDDING_BASE_URL is required when EMBEDDING_PROVIDER=openai_compatible"
            )
        if self.llm_provider == "fake" and self.environment in {
            Environment.STAGING,
            Environment.PRODUCTION,
        }:
            raise ValueError("LLM_PROVIDER=fake is for local development and tests only")
        return self

    @property
    def llm_fallback_list(self) -> list[str]:
        names = [n.strip() for n in self.llm_fallback_providers.split(",") if n.strip()]
        unknown = set(names) - {"ollama", "groq", "gemini", "openrouter"}
        if unknown:
            raise ValueError(f"unknown LLM_FALLBACK_PROVIDERS: {sorted(unknown)}")
        return names

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
