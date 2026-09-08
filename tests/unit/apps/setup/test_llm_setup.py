from apps.setup import llm_setup
from apps.setup.stack import read_env_file
from providers.llm.credentials import CLAUDE_CODE_OAUTH, CODEX_OAUTH, OPENAI_COMPATIBLE, Credential

CODEX = Credential(id="codex_oauth", provider=CODEX_OAUTH, label="Codex CLI login", source="~/.codex/auth.json", models=("gpt-5.5", "gpt-5.4-mini"))
CLAUDE = Credential(id="claude_code_oauth", provider=CLAUDE_CODE_OAUTH, label="Claude Code login", source="Keychain", models=("claude-sonnet-5",))
OPENROUTER = Credential(
    id="openrouter_api_key", provider=OPENAI_COMPATIBLE, label="OpenRouter API key", source="~/.hermes/.env", base_url="https://openrouter.ai/api/v1", models=("openai/gpt-4o-mini",), secret="sk-or-1"
)


def _scripted(*answers):
    answers = list(answers)
    return lambda prompt: answers.pop(0) if answers else ""


def test_interactive_pick_codex_and_model_writes_env(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_setup, "fetch_codex_models", lambda: ["gpt-5.5", "gpt-5.3-codex"])
    monkeypatch.setattr(llm_setup, "verify", lambda env, log: True)
    logs = []

    ok = llm_setup.run(tmp_path, ask=_scripted("1", "2"), log=logs.append, found=[CODEX, CLAUDE, OPENROUTER])

    assert ok
    env = read_env_file(tmp_path / ".env")
    assert env == {"LLM_PROVIDER": "codex_oauth", "LLM_MODEL": "gpt-5.3-codex"}
    assert any("Codex CLI login" in line for line in logs)
    assert any("Skip for now" in line for line in logs)


def test_interactive_pick_api_key_credential_writes_key_and_base_url(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_setup, "verify", lambda env, log: True)

    ok = llm_setup.run(tmp_path, ask=_scripted("3", "1"), log=lambda _: None, found=[CODEX, CLAUDE, OPENROUTER])

    assert ok
    env = read_env_file(tmp_path / ".env")
    assert env["LLM_PROVIDER"] == "openai_compatible"
    assert env["LLM_API_KEY"] == "sk-or-1"
    assert env["LLM_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert env["LLM_MODEL"] == "openai/gpt-4o-mini"


def test_interactive_new_key_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_setup, "verify", lambda env, log: True)
    # options: 1 codex, 2 "enter new key", 3 skip
    ok = llm_setup.run(tmp_path, ask=_scripted("2", "https://api.example.com/v1", "sk-new", "my-model"), log=lambda _: None, found=[CODEX])

    assert ok
    env = read_env_file(tmp_path / ".env")
    assert env == {"LLM_PROVIDER": "openai_compatible", "LLM_BASE_URL": "https://api.example.com/v1", "LLM_API_KEY": "sk-new", "LLM_MODEL": "my-model"}


def test_skip_leaves_env_untouched(tmp_path):
    (tmp_path / ".env").write_text("DATABASE_PATH=./x.db\n")
    ok = llm_setup.run(tmp_path, ask=_scripted("3"), log=lambda _: None, found=[CODEX])
    assert ok is False
    assert (tmp_path / ".env").read_text() == "DATABASE_PATH=./x.db\n"


def test_failed_verification_asks_before_saving(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_setup, "verify", lambda env, log: False)
    ok = llm_setup.run(tmp_path, ask=_scripted("1", "1", "n"), log=lambda _: None, found=[CLAUDE])
    assert ok is False
    assert not (tmp_path / ".env").exists()


def test_non_interactive_yes_takes_first_credential_and_default_model(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_setup, "verify", lambda env, log: True)
    ok = llm_setup.run(tmp_path, assume_yes=True, log=lambda _: None, found=[CLAUDE, CODEX])
    assert ok
    assert read_env_file(tmp_path / ".env") == {"LLM_PROVIDER": "claude_code_oauth", "LLM_MODEL": "claude-sonnet-5"}


def test_non_interactive_provider_and_model_flags(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_setup, "verify", lambda env, log: True)
    ok = llm_setup.run(tmp_path, provider="codex_oauth", model="gpt-5.5", log=lambda _: None, found=[CLAUDE, CODEX])
    assert ok
    assert read_env_file(tmp_path / ".env")["LLM_MODEL"] == "gpt-5.5"


def test_provider_flag_with_no_matching_credential_fails_clearly(tmp_path):
    logs = []
    assert llm_setup.run(tmp_path, provider="codex_oauth", log=logs.append, found=[CLAUDE]) is False
    assert any("no credentials found" in line for line in logs)


def test_env_updates_never_write_a_key_for_oauth_providers():
    assert llm_setup.env_updates_for(CODEX, "gpt-5.5") == {"LLM_PROVIDER": "codex_oauth", "LLM_MODEL": "gpt-5.5"}
    token_env = Credential(id="claude_code_oauth_token_env", provider=CLAUDE_CODE_OAUTH, label="", source="", secret="cc-x")
    assert llm_setup.env_updates_for(token_env, "m")["CLAUDE_CODE_OAUTH_TOKEN"] == "cc-x"
