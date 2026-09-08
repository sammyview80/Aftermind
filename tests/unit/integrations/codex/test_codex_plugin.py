import io
import json

import httpx

from integrations.claude_code import plugin as claude_plugin
from integrations.codex import __main__ as codex_main
from integrations.codex import plugin


def _capture_posts(monkeypatch):
    posts = []

    def fake_post(url, json=None, timeout=None):
        posts.append((url, json))
        request = httpx.Request("POST", url)
        if url.endswith("/recall"):
            return httpx.Response(200, json={"context": "## Current facts\n- Aftermind uses SQLite"}, request=request)
        return httpx.Response(200, json={}, request=request)

    monkeypatch.setattr(claude_plugin.httpx, "post", fake_post)
    # observe_async runs in a thread; make it synchronous for assertions.
    monkeypatch.setattr(claude_plugin.threading, "Thread", _ImmediateThread)
    return posts


class _ImmediateThread:
    def __init__(self, target=None, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def test_user_prompt_submit_recalls_and_observes_with_codex_event_name(monkeypatch):
    posts = _capture_posts(monkeypatch)

    result = plugin.HANDLERS["UserPromptSubmit"]({"prompt": "what did we decide about billing?", "cwd": "/tmp", "session_id": "s"})

    assert result["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "Aftermind uses SQLite" in result["hookSpecificOutput"]["additionalContext"]
    assert any(u.endswith("/observe") for u, _ in posts)
    assert any(u.endswith("/recall") for u, _ in posts)


def test_stop_observes_last_assistant_message(monkeypatch):
    posts = _capture_posts(monkeypatch)

    plugin.HANDLERS["Stop"]({"last_assistant_message": "We decided billing uses RabbitMQ.", "cwd": "/tmp", "session_id": "s"})

    observe = [j for u, j in posts if u.endswith("/observe")]
    assert observe and observe[0]["event_type"] == "agent_message"
    assert observe[0]["output"] == "We decided billing uses RabbitMQ."


def test_stop_ignores_empty_message(monkeypatch):
    posts = _capture_posts(monkeypatch)
    plugin.HANDLERS["Stop"]({"last_assistant_message": None})
    assert posts == []


def test_session_end_spawns_detached_checkpoint_child(monkeypatch):
    spawned = []

    class FakeProc:
        def __init__(self):
            self.stdin = io.BytesIO()

    def fake_popen(cmd, **kwargs):
        spawned.append((cmd, kwargs))
        return FakeProc()

    monkeypatch.setattr(plugin.subprocess, "Popen", fake_popen)

    plugin.HANDLERS["SessionEnd"]({"transcript_path": "/x.jsonl", "cwd": "/tmp"})

    cmd, kwargs = spawned[0]
    assert cmd[-3:] == ["integrations.codex", "--checkpoint", "session_end"]
    assert kwargs["start_new_session"] is True


def test_main_dispatches_on_hook_event_name(monkeypatch, capsys):
    monkeypatch.setattr(plugin, "HANDLERS", {"Stop": lambda payload: {"ok": payload["x"]}})
    monkeypatch.setattr(codex_main, "HANDLERS", plugin.HANDLERS)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "Stop", "x": 1})))

    assert codex_main.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {"ok": 1}


def test_main_checkpoint_mode_runs_checkpoint(monkeypatch):
    calls = []
    monkeypatch.setattr(codex_main, "run_checkpoint", lambda payload, reason: calls.append((payload, reason)))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"transcript_path": "/t"})))

    assert codex_main.main(["--checkpoint", "pre_compact"]) == 0
    assert calls == [({"transcript_path": "/t"}, "pre_compact")]


def test_main_swallows_bad_input(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert codex_main.main([]) == 0
