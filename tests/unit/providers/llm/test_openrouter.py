import json
from io import BytesIO

import pytest

from providers.llm.openrouter import OpenRouterProvider


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        return FakeResponse(self.payload)


def test_complete_posts_openai_compatible_body_and_parses_content():
    opener = FakeOpener({"choices": [{"message": {"content": "hello from the model"}}]})
    provider = OpenRouterProvider(model="openai/gpt-4o-mini", api_key="key123", opener=opener)

    result = provider.complete("some prompt")

    assert result == "hello from the model"
    request = opener.requests[0]
    assert request.full_url == "https://openrouter.ai/api/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer key123"
    body = json.loads(request.data)
    assert body == {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "some prompt"}]}


def test_custom_base_url_is_respected():
    opener = FakeOpener({"choices": [{"message": {"content": "ok"}}]})
    provider = OpenRouterProvider(
        model="m", api_key="k", base_url="https://example.com/v1/", opener=opener
    )

    provider.complete("prompt")

    assert opener.requests[0].full_url == "https://example.com/v1/chat/completions"


def test_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="API key"):
        OpenRouterProvider(model="m", api_key="")


def test_raises_without_model(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    with pytest.raises(ValueError, match="model"):
        OpenRouterProvider(model="", api_key="k")


def test_reads_defaults_from_env_config(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    opener = FakeOpener({"choices": [{"message": {"content": "ok"}}]})

    provider = OpenRouterProvider(opener=opener)

    assert provider.api_key == "env-key"
    assert provider.model == "env-model"
