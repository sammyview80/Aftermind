import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[4] / "sdk" / "python"))
from client import AftermindClient  # noqa: E402


def _client(handler) -> AftermindClient:
    transport = httpx.MockTransport(handler)
    return AftermindClient(http_client=httpx.Client(transport=transport, base_url="http://testserver"))


def test_observe_posts_expected_body_and_returns_json():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"created": True, "memory_id": "m1", "content": "x"})

    result = _client(handler).observe({"tenant_id": "t1"}, output="Team uses PostgreSQL")

    assert captured["path"] == "/observe"
    assert captured["body"] == {
        "scope": {"levels": {"tenant_id": "t1"}},
        "input": "",
        "output": "Team uses PostgreSQL",
        "event_type": "agent_message",
    }
    assert result == {"created": True, "memory_id": "m1", "content": "x"}


def test_recall_posts_scope_text_and_limit():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body == {"scope": {"levels": {"tenant_id": "t1"}}, "text": "continue", "limit": 5}
        return httpx.Response(200, json={"context": "ctx", "memories": [], "related_entities": []})

    result = _client(handler).recall({"tenant_id": "t1"}, text="continue", limit=5)
    assert result["context"] == "ctx"


def test_checkpoint_posts_lists_as_lists():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["completed"] == ["a", "b"]
        return httpx.Response(200, json={"found": True, "checkpoint_id": "c1", "version": 1})

    result = _client(handler).checkpoint({"tenant_id": "t1"}, goal="g", completed=["a", "b"])
    assert result["checkpoint_id"] == "c1"


def test_search_returns_memories():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"memories": [{"memory_id": "m1", "content": "x", "memory_type": "semantic", "confidence": 0.9}]})

    result = _client(handler).search({"tenant_id": "t1"}, query="x")
    assert len(result["memories"]) == 1


def test_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    import pytest

    with pytest.raises(httpx.HTTPStatusError):
        _client(handler).search({"tenant_id": "t1"}, query="x")
