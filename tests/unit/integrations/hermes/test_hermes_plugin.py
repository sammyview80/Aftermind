import time

import httpx
import pytest

from integrations.hermes.hermes_plugin import observe, observe_async, observe_tool_result, observe_turn, recall


def _client_with(monkeypatch, handler):
    def fake_post(url, json=None, timeout=None):
        response = handler(url, json)
        response._request = httpx.Request("POST", url)
        return response

    monkeypatch.setattr(httpx, "post", fake_post)


def test_recall_injects_context_on_hit(monkeypatch):
    captured = {}

    def handler(url, json):
        captured["url"] = url
        captured["body"] = json
        return httpx.Response(200, json={"context": "- Aftermind uses SQLite locally", "memories": []})

    _client_with(monkeypatch, handler)

    result = recall(session_id="s1", user_message="What database does Aftermind use?", is_first_turn=True)

    assert result == {"context": "[Aftermind memory]\n- Aftermind uses SQLite locally"}
    assert captured["url"].endswith("/recall")
    assert captured["body"]["text"] == "What database does Aftermind use?"
    assert captured["body"]["scope"]["levels"]["tenant_id"] == "hermes"


def test_recall_returns_none_on_empty_context(monkeypatch):
    _client_with(monkeypatch, lambda url, json: httpx.Response(200, json={"context": "", "memories": []}))
    assert recall(session_id="s1", user_message="anything", is_first_turn=False) is None


def test_recall_returns_none_on_empty_message():
    assert recall(session_id="s1", user_message="", is_first_turn=True) is None
    assert recall(session_id="s1", user_message="   ", is_first_turn=True) is None


def test_recall_returns_none_on_network_failure(monkeypatch):
    def handler(url, json):
        raise httpx.ConnectError("refused")

    _client_with(monkeypatch, handler)
    assert recall(session_id="s1", user_message="hi", is_first_turn=True) is None


def test_recall_returns_none_on_http_error(monkeypatch):
    _client_with(monkeypatch, lambda url, json: httpx.Response(500, json={"detail": "boom"}))
    assert recall(session_id="s1", user_message="hi", is_first_turn=True) is None


def test_recall_uses_env_config(monkeypatch):
    monkeypatch.setenv("AFTERMIND_URL", "http://example.com:9000")
    monkeypatch.setenv("AFTERMIND_SCOPE_TENANT", "acme")
    monkeypatch.setenv("AFTERMIND_SCOPE_PROJECT", "widgets")
    captured = {}

    def handler(url, json):
        captured["url"] = url
        captured["body"] = json
        return httpx.Response(200, json={"context": "x"})

    _client_with(monkeypatch, handler)
    recall(session_id="s1", user_message="hi", is_first_turn=True)

    assert captured["url"] == "http://example.com:9000/recall"
    assert captured["body"]["scope"]["levels"] == {"tenant_id": "acme", "project_id": "widgets"}


def test_observe_posts_to_observe_endpoint(monkeypatch):
    captured = {}

    def handler(url, json):
        captured["url"] = url
        captured["body"] = json
        return httpx.Response(200, json={"created": True})

    _client_with(monkeypatch, handler)
    observe("We decided Aftermind will use SQLite for local persistence.", "user_message")

    assert captured["url"].endswith("/observe")
    assert captured["body"]["output"] == "We decided Aftermind will use SQLite for local persistence."
    assert captured["body"]["event_type"] == "user_message"
    assert captured["body"]["scope"]["levels"]["tenant_id"] == "hermes"


def test_observe_skips_empty_text(monkeypatch):
    calls = []
    _client_with(monkeypatch, lambda url, json: calls.append(1) or httpx.Response(200, json={}))
    observe("", "user_message")
    observe("   ", "user_message")
    assert calls == []


def test_observe_swallows_network_failure(monkeypatch):
    def handler(url, json):
        raise httpx.ConnectError("refused")

    _client_with(monkeypatch, handler)
    observe("some fact", "user_message")  # must not raise


def test_observe_async_runs_in_background_and_does_not_block(monkeypatch):
    captured = {}
    release = threading_event = __import__("threading").Event()

    def handler(url, json):
        threading_event.wait(timeout=2)
        captured["body"] = json
        return httpx.Response(200, json={})

    _client_with(monkeypatch, handler)

    started = time.monotonic()
    observe_async("some fact", "user_message")
    elapsed = time.monotonic() - started

    assert elapsed < 0.5  # returned immediately, didn't wait on the slow handler
    threading_event.set()
    time.sleep(0.2)  # let the background thread finish
    assert captured["body"]["output"] == "some fact"


def test_observe_turn_observes_user_message_and_assistant_response(monkeypatch):
    seen = []

    def handler(url, json):
        seen.append(json)
        return httpx.Response(200, json={})

    _client_with(monkeypatch, handler)
    observe_turn(
        session_id="s1",
        user_message="We decided Aftermind will use SQLite for local persistence.",
        assistant_response="Got it, noted.",
    )
    time.sleep(0.2)

    outputs = {call["output"]: call["event_type"] for call in seen}
    assert outputs["We decided Aftermind will use SQLite for local persistence."] == "user_message"
    assert outputs["Got it, noted."] == "agent_message"


def test_observe_tool_result_captures_result_and_truncates(monkeypatch):
    seen = []
    _client_with(monkeypatch, lambda url, json: seen.append(json) or httpx.Response(200, json={}))

    observe_tool_result(tool_name="read_file", args={"path": "x.py"}, result="A" * 1000, status="success")
    time.sleep(0.2)

    assert len(seen) == 1
    assert seen[0]["event_type"] == "tool_completed"
    assert seen[0]["output"].startswith("Tool read_file result: AAA")
    assert len(seen[0]["output"]) <= len("Tool read_file result: ") + 500


def test_observe_tool_result_maps_error_status_to_tool_failed(monkeypatch):
    seen = []
    _client_with(monkeypatch, lambda url, json: seen.append(json) or httpx.Response(200, json={}))

    observe_tool_result(tool_name="run_command", params={}, result="permission denied", status="error")
    time.sleep(0.2)

    assert seen[0]["event_type"] == "tool_failed"


def test_observe_tool_result_tolerates_missing_fields(monkeypatch):
    seen = []
    _client_with(monkeypatch, lambda url, json: seen.append(json) or httpx.Response(200, json={}))

    observe_tool_result()  # no kwargs at all — must not raise
    time.sleep(0.2)

    assert seen[0]["output"] == "Tool unknown_tool result: None"
    assert seen[0]["event_type"] == "tool_completed"

