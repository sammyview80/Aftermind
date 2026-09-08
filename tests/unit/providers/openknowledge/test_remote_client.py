import json
import urllib.error

from providers.openknowledge.remote_client import RemoteOpenKnowledgeClient, _doc_name, _embed_meta, _parse_meta


class FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_doc_name_sanitizes_scope_key_for_a_path_segment():
    assert _doc_name("slug", "t1:*:aftermind") == "t1_unscoped_aftermind/slug.md"


def test_embed_and_parse_meta_round_trips():
    data = {"title": "Doc", "sections": [], "version": 1}
    markdown = _embed_meta(data, "# Doc\n\nbody")
    assert markdown.startswith("<!--aftermind-meta:")
    assert "# Doc" in markdown
    assert _parse_meta(markdown) == data


def test_parse_meta_returns_none_without_meta_comment():
    assert _parse_meta("# Just a doc\n\nno meta here") is None


def test_write_posts_to_agent_write_md(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        return FakeHTTPResponse({"ok": True})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = RemoteOpenKnowledgeClient("http://127.0.0.1:65425")
    client.write("aftermind-architecture", "t1", {"title": "Doc", "sections": []}, "# Doc")

    assert captured["url"] == "http://127.0.0.1:65425/api/agent-write-md"
    assert captured["body"]["docName"] == "t1/aftermind-architecture.md"
    assert captured["body"]["markdown"].startswith("<!--aftermind-meta:")


def test_read_gets_document_and_parses_meta(monkeypatch):
    data = {"title": "Doc", "sections": []}
    markdown = _embed_meta(data, "# Doc")

    def fake_urlopen(request, timeout=None):
        assert "docName=t1%2Fdoc.md" in request.full_url
        return FakeHTTPResponse({"docName": "t1/doc.md", "content": markdown})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = RemoteOpenKnowledgeClient("http://127.0.0.1:65425")
    result = client.read("doc", "t1")

    assert result == data


def test_read_returns_none_on_404(monkeypatch):
    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = RemoteOpenKnowledgeClient("http://127.0.0.1:65425")
    assert client.read("nonexistent", "t1") is None


def test_search_filters_documents_by_scope_and_content(monkeypatch):
    scoped_data = {"title": "Aftermind Architecture", "sections": [{"heading": "Overview", "body": "uses a reconciler"}]}
    other_scope_data = {"title": "Other Doc", "sections": [{"heading": "X", "body": "reconciler mention"}]}
    unrelated_data = {"title": "Billing", "sections": [{"heading": "X", "body": "invoices"}]}

    documents_listing = {
        "documents": [
            {"kind": "document", "docName": "t1/arch.md"},
            {"kind": "document", "docName": "t1/unrelated.md"},
            {"kind": "document", "docName": "t2/other.md"},
            {"kind": "folder", "docName": "t1"},
        ]
    }

    def fake_urlopen(request, timeout=None):
        url = request.full_url
        if "/api/documents" in url:
            return FakeHTTPResponse(documents_listing)
        if "docName=t1%2Farch.md" in url:
            return FakeHTTPResponse({"content": _embed_meta(scoped_data, "")})
        if "docName=t1%2Funrelated.md" in url:
            return FakeHTTPResponse({"content": _embed_meta(unrelated_data, "")})
        if "docName=t2%2Fother.md" in url:
            return FakeHTTPResponse({"content": _embed_meta(other_scope_data, "")})
        raise AssertionError(f"unexpected request: {url}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = RemoteOpenKnowledgeClient("http://127.0.0.1:65425")
    results = client.search("reconciler", scope_key="t1")

    assert len(results) == 1
    assert results[0]["title"] == "Aftermind Architecture"
