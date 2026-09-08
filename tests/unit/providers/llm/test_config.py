from providers.llm.config import DEFAULT_BASE_URL, get_llm_config


def test_reads_from_environment(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "key123")
    monkeypatch.setenv("LLM_MODEL", "openai/gpt-4o-mini")
    monkeypatch.setenv("LLM_BASE_URL", "https://example.com/v1")

    config = get_llm_config()

    assert config.api_key == "key123"
    assert config.model == "openai/gpt-4o-mini"
    assert config.base_url == "https://example.com/v1"


def test_base_url_defaults_to_openrouter(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    assert get_llm_config().base_url == DEFAULT_BASE_URL


def test_missing_api_key_and_model_are_empty_strings(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    config = get_llm_config()

    assert config.api_key == ""
    assert config.model == ""
