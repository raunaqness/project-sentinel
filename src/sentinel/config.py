"""Typed application settings, loaded from environment variables (prefix SENTINEL_)."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
