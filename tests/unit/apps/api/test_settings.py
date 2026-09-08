import pytest

from apps.api.settings import Settings


def test_defaults_when_env_is_empty(monkeypatch):
    for key in (
        "DATABASE_PATH",
        "AFTERMIND_SYNC_MODE",
        "AFTERMIND_SYNC_WORKER",
        "AFTERMIND_LOG_FORMAT",
        "NEO4J_PASSWORD",
        "OPENKNOWLEDGE_URL",
    ):
        monkeypatch.delenv(key, raising=False)

    settings = Settings.from_env()

    assert settings.database_path == "./aftermind.db"
    assert settings.sync_mode == "eager"
    assert settings.sync_worker_enabled is True
    assert settings.graph_backend == "inmemory"
    assert settings.document_backend == "local_markdown"


def test_env_overrides_and_redaction(monkeypatch):
    monkeypatch.setenv("AFTERMIND_SYNC_MODE", "background")
    monkeypatch.setenv("AFTERMIND_SYNC_WORKER", "false")
    monkeypatch.setenv("AFTERMIND_LOG_FORMAT", "json")
    monkeypatch.setenv("NEO4J_PASSWORD", "hunter2")
    monkeypatch.setenv("LLM_API_KEY", "sk-x")

    settings = Settings.from_env()

    assert settings.sync_mode == "background"
    assert settings.sync_worker_enabled is False
    assert settings.log_format == "json"
    assert settings.graph_backend == "neo4j"
    redacted = settings.redacted()
    assert redacted["neo4j_password"] == "***"
    assert redacted["llm_api_key"] == "***"
    assert "hunter2" not in str(redacted)


def test_invalid_sync_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("AFTERMIND_SYNC_MODE", "maybe")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_invalid_log_format_is_rejected(monkeypatch):
    monkeypatch.delenv("AFTERMIND_SYNC_MODE", raising=False)
    monkeypatch.setenv("AFTERMIND_LOG_FORMAT", "xml")
    with pytest.raises(ValueError):
        Settings.from_env()
