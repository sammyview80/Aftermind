import json

import httpx
import pytest

from integrations.claude_code.plugin import (
    on_post_tool_use,
    on_post_tool_use_failure,
    on_session_end,
    on_session_start,
    on_user_prompt_submit,
)


def _client_with(monkeypatch, handler):
    def fake_post(url, json=None, timeout=None):
        response = handler(url, json)
        response._request = httpx.Request("POST", url)
        return response

    monkeypatch.setattr(httpx, "post", fake_post)


def test_on_user_prompt_submit_injects_context_via_hook_specific_output(monkeypatch):
    captured = {}

    def handler(url, json):
        if url.endswith("/observe"):
            return httpx.Response(200, json={})
        captured["url"] = url
        captured["body"] = json
        return httpx.Response(200, json={"context": "- Aftermind uses SQLite", "memories": []})

    _client_with(monkeypatch, handler)

    result = on_user_prompt_submit({"user_prompt": "What database does Aftermind use?", "cwd": "/tmp", "session_id": "s1"})

    assert result == {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": "[Aftermind memory]\n- Aftermind uses SQLite",
        }
    }
    assert captured["url"].endswith("/recall")
    assert captured["body"]["text"] == "What database does Aftermind use?"


def test_on_user_prompt_submit_returns_none_on_empty_context(monkeypatch):
    _client_with(monkeypatch, lambda url, json: httpx.Response(200, json={"context": "", "memories": []}))
    assert on_user_prompt_submit({"user_prompt": "hi"}) is None


def test_on_user_prompt_submit_returns_none_on_empty_prompt(monkeypatch):
    calls = []
    _client_with(monkeypatch, lambda url, json: calls.append(url) or httpx.Response(200, json={"context": "x"}))
    assert on_user_prompt_submit({"user_prompt": ""}) is None
    # Still fine to have attempted an observe (skipped internally for empty text) —
    # just no recall call should have gone out for empty text either.


def test_on_user_prompt_submit_returns_none_on_network_failure(monkeypatch):
    def handler(url, json):
        raise httpx.ConnectError("refused")

    _client_with(monkeypatch, handler)
    assert on_user_prompt_submit({"user_prompt": "hi"}) is None


def test_on_session_start_injects_context_when_available(monkeypatch):
    _client_with(monkeypatch, lambda url, json: httpx.Response(200, json={"context": "## Where you left off\nGoal: X"}))

    result = on_session_start({"cwd": "/tmp", "session_id": "s1"})

    assert result["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Goal: X" in result["hookSpecificOutput"]["additionalContext"]


def test_on_session_start_returns_none_when_nothing_to_recall(monkeypatch):
    _client_with(monkeypatch, lambda url, json: httpx.Response(200, json={"context": ""}))
    assert on_session_start({"cwd": "/tmp"}) is None


def test_on_post_tool_use_observes_tool_completion(monkeypatch):
    seen = []
    _client_with(monkeypatch, lambda url, json: seen.append(json) or httpx.Response(200, json={}))

    on_post_tool_use({"tool_name": "Bash", "tool_result": "exit 0", "cwd": "/tmp"})
    import time

    time.sleep(0.2)

    assert len(seen) == 1
    assert seen[0]["event_type"] == "tool_completed"
    assert "Bash" in seen[0]["output"]


def test_on_post_tool_use_failure_observes_tool_failure(monkeypatch):
    seen = []
    _client_with(monkeypatch, lambda url, json: seen.append(json) or httpx.Response(200, json={}))

    on_post_tool_use_failure({"tool_name": "Bash", "tool_result": "permission denied", "cwd": "/tmp"})
    import time

    time.sleep(0.2)

    assert seen[0]["event_type"] == "tool_failed"


def test_on_session_end_checkpoints_from_transcript(monkeypatch, tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        "\n".join(
            [
                json.dumps({"type": "user", "message": {"role": "user", "content": "We finished X."}}),
                json.dumps(
                    {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Noted."}]}}
                ),
            ]
        )
    )

    checkpoint_calls = []

    def handler(url, json):
        if url.endswith("/checkpoint/from-text"):
            checkpoint_calls.append(json)
        return httpx.Response(200, json={})

    _client_with(monkeypatch, handler)

    on_session_end({"transcript_path": str(transcript), "cwd": "/tmp", "session_id": "s1"})

    assert len(checkpoint_calls) == 1
    assert "We finished X." in checkpoint_calls[0]["text"]
    assert checkpoint_calls[0]["reason"] == "session_end"


def test_on_session_end_is_a_noop_with_no_transcript(monkeypatch):
    calls = []
    _client_with(monkeypatch, lambda url, json: calls.append(json) or httpx.Response(200, json={}))

    on_session_end({"transcript_path": None})

    assert calls == []
