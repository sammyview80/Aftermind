import json

from apps.setup import connectors


def test_merge_hooks_replaces_only_our_entries():
    settings = {
        "hooks": {
            "UserPromptSubmit": [
                {"matcher": ".*", "hooks": [{"type": "command", "command": "other-tool run", "timeout": 1}]},
                {"matcher": ".*", "hooks": [{"type": "command", "command": "cd /old && python -m integrations.claude_code", "timeout": 5000}]},
            ]
        }
    }
    connectors.merge_hooks(
        settings, {"UserPromptSubmit": 5000, "SessionEnd": 15000}, "cd /new && python -m integrations.claude_code", "integrations.claude_code", ".*"
    )
    prompt_hooks = settings["hooks"]["UserPromptSubmit"]
    assert len(prompt_hooks) == 2
    assert prompt_hooks[0]["hooks"][0]["command"] == "other-tool run"
    assert prompt_hooks[1]["hooks"][0]["command"].startswith("cd /new")
    assert settings["hooks"]["SessionEnd"][0]["hooks"][0]["timeout"] == 15000

    # Re-running does not duplicate.
    connectors.merge_hooks(
        settings, {"UserPromptSubmit": 5000}, "cd /new && python -m integrations.claude_code", "integrations.claude_code", ".*"
    )
    assert len(settings["hooks"]["UserPromptSubmit"]) == 2


def test_connect_claude_code_writes_all_six_events_and_backs_up(tmp_path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"model": "opus", "hooks": {"PreToolUse": [{"hooks": []}]}}))
    logs = []

    connectors.connect_claude_code(tmp_path, settings_path=settings_path, register_mcp=False, log=logs.append)

    written = json.loads(settings_path.read_text())
    assert written["model"] == "opus"  # untouched
    assert set(connectors.CLAUDE_CODE_HOOKS) <= set(written["hooks"])
    assert written["hooks"]["PreToolUse"] == [{"hooks": []}]
    command = written["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
    assert str(tmp_path) in command and "integrations.claude_code" in command
    assert written["hooks"]["UserPromptSubmit"][0]["matcher"] == ".*"
    assert list(tmp_path.glob("settings.json.bak-*"))


def test_connect_codex_uses_seconds_and_caps_session_end(tmp_path):
    hooks_path = tmp_path / "hooks.json"

    connectors.connect_codex(tmp_path, hooks_path=hooks_path, register_mcp=False, log=lambda _: None)

    written = json.loads(hooks_path.read_text())
    assert set(connectors.CODEX_HOOKS) <= set(written["hooks"])
    session_end = written["hooks"]["SessionEnd"][0]["hooks"][0]
    assert session_end["timeout"] <= 3
    assert "integrations.codex" in session_end["command"]
    assert "matcher" not in written["hooks"]["SessionEnd"][0]
    assert "Stop" in written["hooks"]


def test_connect_hermes_links_plugin_and_edits_config_idempotently(tmp_path):
    repo = tmp_path / "repo"
    (repo / "integrations" / "hermes" / "hermes_plugin").mkdir(parents=True)
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text(
        "model: x\n"
        "mcp_servers:\n"
        "  other:\n"
        "    command: /bin/other\n"
        "plugins:\n"
        "  enabled:\n"
        "    - something\n"
        "  disabled: []\n"
        "platform_toolsets:\n"
        "  cli: true\n"
    )

    connectors.connect_hermes(repo, hermes_home=home, log=lambda _: None)
    connectors.connect_hermes(repo, hermes_home=home, log=lambda _: None)

    link = home / "plugins" / "aftermind"
    assert link.is_symlink()
    text = (home / "config.yaml").read_text()
    assert text.count("    - aftermind") == 1
    assert text.count("  aftermind:\n") == 1
    assert "url: http://127.0.0.1:8000/mcp/" in text
    assert "  other:\n    command: /bin/other" in text
    assert "platform_toolsets:\n  cli: true" in text
    assert text.index("  aftermind:") < text.index("plugins:")  # stayed inside mcp_servers


def test_connect_hermes_creates_sections_when_absent(tmp_path):
    repo = tmp_path / "repo"
    (repo / "integrations" / "hermes" / "hermes_plugin").mkdir(parents=True)
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text("model: x\n")

    connectors.connect_hermes(repo, hermes_home=home, log=lambda _: None)

    text = (home / "config.yaml").read_text()
    assert "plugins:\n  enabled:\n    - aftermind" in text
    assert "mcp_servers:\n  aftermind:\n    url:" in text
