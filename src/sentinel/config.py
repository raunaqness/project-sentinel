"""Typed application settings, loaded from environment variables (prefix SENTINEL_)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SENTINEL_",
        env_file=".env",
        extra="ignore",
    )

    environment: Literal["local", "test", "production"] = "local"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    database_url: PostgresDsn = Field(
        default=PostgresDsn("postgresql+asyncpg://sentinel:sentinel@localhost:5432/sentinel"),
    )
    kafka_bootstrap_servers: str = "localhost:19092"
    redis_url: RedisDsn = Field(default=RedisDsn("redis://localhost:6379/0"))

    # Reconciliation timing
    missing_settlement_seconds: int = 86_400  # settlement expected within 24h of capture
    reconciliation_grace_seconds: int = 300  # tolerance for normal async arrival
    scheduler_interval_seconds: int = 30

    # Investigation workflow
    lease_seconds: int = 60  # a claimed job is reclaimable this long after the last heartbeat
    max_attempts: int = 3
    worker_poll_seconds: float = 1.0

    # OpenRouter (OpenAI-compatible API) for embeddings and, later, the LLM
    openrouter_api_key: SecretStr | None = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # AI investigator
    investigator: Literal["mock", "openrouter"] = "mock"  # tests/CI never call a paid model
    llm_model: str = "openai/gpt-4o-mini"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2  # SDK retries 429/5xx/timeouts with exponential backoff

    # Knowledge base and retrieval
    embedder: Literal["fake", "openrouter"] = "fake"  # fake = deterministic, offline
    embedding_model: str = "openai/text-embedding-3-small"  # 1536 dimensions
    knowledge_base_dir: str = "knowledge_base"
    retrieval_top_k: int = 5

    # Failure injection (spec §21). Name kept exactly as in the brief: FAIL_AFTER_STEP.
    # Applies to the first attempt of each investigation, so a restarted worker recovers.
    fail_after_step: str | None = Field(default=None, validation_alias="FAIL_AFTER_STEP")
    # Dev/test only: honour `metadata.fail_after_step` on events for per-investigation faults.
    allow_fault_injection: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
