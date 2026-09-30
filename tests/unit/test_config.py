from sentinel.config import Settings


def test_defaults_load() -> None:
    settings = Settings()
    assert settings.environment == "local"
    assert settings.database_url.scheme == "postgresql+asyncpg"


def test_env_override(monkeypatch) -> None:
    monkeypatch.setenv("SENTINEL_ENVIRONMENT", "test")
    monkeypatch.setenv("SENTINEL_KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092")
    settings = Settings()
    assert settings.environment == "test"
    assert settings.kafka_bootstrap_servers == "redpanda:9092"
