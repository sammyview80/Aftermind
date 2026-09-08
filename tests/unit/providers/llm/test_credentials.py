import base64
import json
import time

from providers.llm import credentials as c


def _jwt(claims: dict) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJSUzI1NiJ9.{payload}.sig"


def _fake_home(tmp_path, codex_tokens=True, codex_key="", claude=True):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".claude").mkdir(parents=True)
    (home / ".hermes").mkdir(parents=True)
    codex = {"auth_mode": "chatgpt", "OPENAI_API_KEY": codex_key, "tokens": {}}
    if codex_tokens:
        access = _jwt(
            {
                "exp": int(time.time()) + 3600,
                "https://api.openai.com/auth": {"chatgpt_account_id": "acct_123"},
                "https://api.openai.com/profile": {"email": "me@example.com"},
            }
        )
        codex["tokens"] = {"access_token": access, "refresh_token": "rt", "id_token": "", "account_id": "acct_123"}
    (home / ".codex" / "auth.json").write_text(json.dumps(codex))
    if claude:
        (home / ".claude" / ".credentials.json").write_text(
            json.dumps({"claudeAiOauth": {"accessToken": "cc-token", "refreshToken": "cc-refresh", "expiresAt": int(time.time() * 1000) + 3_600_000}})
        )
    return home


def test_discovers_codex_login_with_account_and_claude_code_file(tmp_path):
    home = _fake_home(tmp_path)

    found = c.discover_credentials(env={}, home=home, include_keychain=False)

    ids = [f.id for f in found]
    assert ids[:2] == ["codex_oauth", "claude_code_oauth"]
    codex = found[0]
    assert codex.provider == c.CODEX_OAUTH
    assert "me@example.com" in codex.label
    assert codex.base_url == c.CODEX_BASE_URL
    assert codex.secret == ""  # OAuth: provider reads tokens itself
    assert found[1].source == "~/.claude/.credentials.json"


def test_expired_codex_token_is_still_offered_but_flagged(tmp_path):
    home = _fake_home(tmp_path, claude=False)
    expired = _jwt({"exp": int(time.time()) - 10})
    auth = json.loads((home / ".codex" / "auth.json").read_text())
    auth["tokens"]["access_token"] = expired
    (home / ".codex" / "auth.json").write_text(json.dumps(auth))

    found = c.discover_credentials(env={}, home=home, include_keychain=False)

    assert found[0].id == "codex_oauth"
    assert "expired" in found[0].label


def test_api_keys_from_env_and_hermes_env_are_offered_after_oauth(tmp_path):
    home = _fake_home(tmp_path, codex_tokens=False, claude=False)
    (home / ".hermes" / ".env").write_text("export OPENROUTER_API_KEY='sk-or-hermes'\nOPENAI_API_KEY=sk-openai\n")

    found = c.discover_credentials(env={"ANTHROPIC_API_KEY": "sk-ant-api-x"}, home=home, include_keychain=False)

    by_id = {f.id: f for f in found}
    assert by_id["openrouter_api_key"].secret == "sk-or-hermes"
    assert by_id["openrouter_api_key"].source == "~/.hermes/.env OPENROUTER_API_KEY"
    assert by_id["openai_api_key"].base_url == c.OPENAI_BASE_URL
    assert by_id["anthropic_api_key"].source == "environment $ANTHROPIC_API_KEY"
    assert all(f.provider == c.OPENAI_COMPATIBLE for f in found)


def test_codex_stored_openai_key_is_offered_and_deduped(tmp_path):
    home = _fake_home(tmp_path, codex_tokens=False, codex_key="sk-openai", claude=False)

    found = c.discover_credentials(env={"OPENAI_API_KEY": "sk-openai"}, home=home, include_keychain=False)

    assert [f.id for f in found] == ["codex_openai_key"]  # same secret from env not repeated


def test_claude_code_prefers_the_valid_source(tmp_path):
    home = _fake_home(tmp_path, codex_tokens=False)
    stale = {"claudeAiOauth": {"accessToken": "old", "refreshToken": "r", "expiresAt": 1}}
    (home / ".claude" / ".credentials.json").write_text(json.dumps(stale))

    class Result:
        returncode = 0
        stdout = json.dumps({"claudeAiOauth": {"accessToken": "fresh", "refreshToken": "r2", "expiresAt": int(time.time() * 1000) + 10_000_000}})

    creds = c.read_claude_code_credentials(home, runner=lambda *a, **k: Result())
    assert creds["accessToken"] == "fresh"
    assert creds["source"] == "macos_keychain"


def test_nothing_found_returns_empty(tmp_path):
    home = tmp_path / "empty"
    home.mkdir()
    assert c.discover_credentials(env={}, home=home, include_keychain=False) == []


def test_jwt_helpers():
    token = _jwt({"exp": int(time.time()) + 100, "https://api.openai.com/auth": {"chatgpt_account_id": "a1"}})
    assert c.codex_account_id(token) == "a1"
    assert c.jwt_expired(token) is False
    assert c.jwt_expired("not-a-jwt") is None
