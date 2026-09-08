import base64
import io
import json
import time
from types import SimpleNamespace

import pytest

from providers.llm import claude_code_oauth, codex_oauth, credentials
from providers.llm.factory import build_llm_provider, llm_configured, llm_provider_id
from providers.llm.token_store import TokenStore


def _jwt(exp_offset: int, account: str = "acct_1") -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({"exp": int(time.time()) + exp_offset, "https://api.openai.com/auth": {"chatgpt_account_id": account}}).encode()
    ).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{payload}.sig"


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ------------------------------------------------------------------ codex


class FakeCodexClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []
        self.responses = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return iter(
            [
                SimpleNamespace(type="response.created"),
                SimpleNamespace(type="response.output_text.delta", delta="O"),
                SimpleNamespace(type="response.output_text.delta", delta="K"),
                SimpleNamespace(type="response.completed"),
            ]
        )


def test_codex_provider_uses_cli_token_and_required_headers(tmp_path, monkeypatch):
    access = _jwt(3600)
    monkeypatch.setattr(codex_oauth, "read_codex_auth", lambda: {"tokens": {"access_token": access, "refresh_token": "rt"}})
    made = []

    def factory(**kwargs):
        client = FakeCodexClient(**kwargs)
        made.append(client)
        return client

    provider = codex_oauth.CodexOAuthProvider(model="gpt-5.4-mini", token_store=TokenStore(tmp_path / "c.json"), client_factory=factory)

    assert provider.complete("hi") == "OK"
    client = made[0]
    assert client.kwargs["api_key"] == access
    assert client.kwargs["base_url"] == credentials.CODEX_BASE_URL
    assert client.kwargs["default_headers"]["ChatGPT-Account-ID"] == "acct_1"
    assert client.kwargs["default_headers"]["originator"] == "codex_cli_rs"
    call = client.calls[0]
    assert call["model"] == "gpt-5.4-mini" and call["store"] is False and call["stream"] is True
    assert call["input"][0]["content"][0]["text"] == "hi"


def test_codex_provider_refreshes_expired_token_and_stores_it_privately(tmp_path, monkeypatch):
    expired, fresh = _jwt(-10), _jwt(3600)
    monkeypatch.setattr(codex_oauth, "read_codex_auth", lambda: {"tokens": {"access_token": expired, "refresh_token": "rt-old"}})
    posted = []

    def opener(request, timeout=None):
        posted.append(request)
        return FakeResponse(json.dumps({"access_token": fresh, "refresh_token": "rt-new"}).encode())

    store = TokenStore(tmp_path / "creds.json")
    provider = codex_oauth.CodexOAuthProvider(token_store=store, client_factory=lambda **k: FakeCodexClient(**k), opener=opener)

    provider.complete("x")

    assert posted[0].full_url == codex_oauth.CODEX_OAUTH_TOKEN_URL
    assert b"client_id=app_EMoamEEZ73f0CkXaXp7hrann" in posted[0].data
    assert store.get("codex_oauth")["refresh_token"] == "rt-new"
    assert oct((tmp_path / "creds.json").stat().st_mode)[-3:] == "600"

    # Next call: our refreshed pair is valid, no second refresh.
    provider.complete("y")
    assert len(posted) == 1


def test_codex_provider_without_any_login_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(codex_oauth, "read_codex_auth", lambda: None)
    provider = codex_oauth.CodexOAuthProvider(token_store=TokenStore(tmp_path / "c.json"), client_factory=lambda **k: FakeCodexClient(**k))
    with pytest.raises(ValueError, match="codex login"):
        provider.complete("x")


# ------------------------------------------------------------ claude code


def test_claude_code_provider_sends_oauth_identity_headers(tmp_path, monkeypatch):
    monkeypatch.setattr(
        claude_code_oauth,
        "read_claude_code_credentials",
        lambda: {"accessToken": "cc-abc", "refreshToken": "r", "expiresAt": int(time.time() * 1000) + 10_000_000},
    )
    monkeypatch.setattr(claude_code_oauth, "claude_code_version", lambda: "2.1.99")
    sent = []

    def opener(request, timeout=None):
        sent.append(request)
        return FakeResponse(json.dumps({"content": [{"type": "text", "text": "OK"}]}).encode())

    provider = claude_code_oauth.ClaudeCodeOAuthProvider(model="claude-sonnet-5", token_store=TokenStore(tmp_path / "c.json"), opener=opener)

    assert provider.complete("hi") == "OK"
    request = sent[0]
    assert request.full_url == "https://api.anthropic.com/v1/messages"
    assert request.get_header("Authorization") == "Bearer cc-abc"
    assert request.get_header("Anthropic-beta") == claude_code_oauth.OAUTH_BETAS
    assert request.get_header("X-app") == "cli"
    assert "claude-cli/2.1.99" in request.get_header("User-agent")
    body = json.loads(request.data)
    assert body["system"][0]["text"] == claude_code_oauth.CLAUDE_CODE_SYSTEM_PREFIX
    assert body["messages"] == [{"role": "user", "content": "hi"}]


def test_claude_code_provider_refreshes_when_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(
        claude_code_oauth, "read_claude_code_credentials", lambda: {"accessToken": "old", "refreshToken": "r-old", "expiresAt": 1}
    )
    monkeypatch.setattr(claude_code_oauth, "claude_code_version", lambda: "2.1.99")
    sent = []

    def opener(request, timeout=None):
        sent.append(request)
        if "oauth/token" in request.full_url:
            return FakeResponse(json.dumps({"access_token": "new", "refresh_token": "r-new", "expires_in": 3600}).encode())
        return FakeResponse(json.dumps({"content": [{"type": "text", "text": "OK"}]}).encode())

    store = TokenStore(tmp_path / "c.json")
    provider = claude_code_oauth.ClaudeCodeOAuthProvider(token_store=store, opener=opener)

    provider.complete("hi")

    assert sent[0].full_url == claude_code_oauth.OAUTH_TOKEN_URLS[0]
    assert b"client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e" in sent[0].data
    assert sent[1].get_header("Authorization") == "Bearer new"
    assert store.get("claude_code_oauth")["refreshToken"] == "r-new"


def test_claude_code_fixed_token_skips_credential_files(tmp_path, monkeypatch):
    monkeypatch.setattr(claude_code_oauth, "read_claude_code_credentials", lambda: None)
    monkeypatch.setattr(claude_code_oauth, "claude_code_version", lambda: "2.1.99")
    sent = []

    def opener(request, timeout=None):
        sent.append(request)
        return FakeResponse(json.dumps({"content": [{"type": "text", "text": "OK"}]}).encode())

    claude_code_oauth.ClaudeCodeOAuthProvider(access_token="cc-env", opener=opener).complete("hi")
    assert sent[0].get_header("Authorization") == "Bearer cc-env"


# ---------------------------------------------------------------- factory


def test_factory_selects_provider_from_env():
    assert llm_provider_id({}) == "openai_compatible"
    assert llm_provider_id({"LLM_PROVIDER": "Codex_OAuth"}) == "codex_oauth"
    with pytest.raises(ValueError):
        llm_provider_id({"LLM_PROVIDER": "bogus"})

    assert isinstance(build_llm_provider({"LLM_PROVIDER": "codex_oauth", "LLM_MODEL": "gpt-5.5"}), codex_oauth.CodexOAuthProvider)
    claude = build_llm_provider({"LLM_PROVIDER": "claude_code_oauth", "CLAUDE_CODE_OAUTH_TOKEN": "cc-x"})
    assert isinstance(claude, claude_code_oauth.ClaudeCodeOAuthProvider)
    assert claude._fixed_token == "cc-x"


def test_llm_configured_semantics():
    assert llm_configured({}) is False
    assert llm_configured({"LLM_API_KEY": "k"}) is False
    assert llm_configured({"LLM_API_KEY": "k", "LLM_MODEL": "m"}) is True
    assert llm_configured({"LLM_PROVIDER": "codex_oauth"}) is True
    assert llm_configured({"LLM_PROVIDER": "nope"}) is False
