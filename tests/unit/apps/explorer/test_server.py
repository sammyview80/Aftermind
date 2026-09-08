from unittest.mock import patch

from fastapi.testclient import TestClient

from apps.explorer import server


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_documents_filters_to_markdown_documents_scoped_to_prefix(monkeypatch):
    monkeypatch.setattr(server, "OPENKNOWLEDGE_URL", "http://fake-ok")
    raw = {
        "documents": [
            {"docName": "t1_unscoped/aftermind-architecture.md", "kind": "document", "title": "x"},
            {"docName": "other_scope/notes.md", "kind": "document"},
            {"docName": ".gitignore", "kind": "document"},  # not a knowledge page
            {"docName": "t1_unscoped/readme.txt", "kind": "document"},  # not markdown
        ]
    }
    with patch.object(server.httpx, "get", return_value=FakeResponse(raw)):
        client = TestClient(server.app)
        response = client.get("/api/documents", params={"scope_key": "t1:*"})

    assert response.status_code == 200
    docs = response.json()["documents"]
    assert [d["path"] for d in docs] == ["t1_unscoped/aftermind-architecture.md"]


def test_documents_unfiltered_returns_all_markdown_pages(monkeypatch):
    monkeypatch.setattr(server, "OPENKNOWLEDGE_URL", "http://fake-ok")
    raw = {"documents": [{"docName": "a/one.md", "kind": "document"}, {"docName": "b/two.md", "kind": "document"}]}
    with patch.object(server.httpx, "get", return_value=FakeResponse(raw)):
        client = TestClient(server.app)
        response = client.get("/api/documents")

    assert {d["path"] for d in response.json()["documents"]} == {"a/one.md", "b/two.md"}


def test_documents_unavailable_when_openknowledge_not_configured(monkeypatch):
    monkeypatch.setattr(server, "OPENKNOWLEDGE_URL", "")
    client = TestClient(server.app)
    response = client.get("/api/documents")

    assert response.json() == {"documents": [], "available": False}


def test_document_content_strips_embedded_metadata_comment(monkeypatch):
    monkeypatch.setattr(server, "OPENKNOWLEDGE_URL", "http://fake-ok")
    raw = {"content": '<!--aftermind-meta:{"version":1}-->\n\n# Title\n\nBody text.'}
    with patch.object(server.httpx, "get", return_value=FakeResponse(raw)):
        client = TestClient(server.app)
        response = client.get("/api/documents/content", params={"path": "x.md"})

    assert response.json() == {"markdown": "# Title\n\nBody text."}


def test_document_content_passes_through_plain_markdown(monkeypatch):
    monkeypatch.setattr(server, "OPENKNOWLEDGE_URL", "http://fake-ok")
    with patch.object(server.httpx, "get", return_value=FakeResponse({"content": "# No metadata here"})):
        client = TestClient(server.app)
        response = client.get("/api/documents/content", params={"path": "x.md"})

    assert response.json() == {"markdown": "# No metadata here"}


def test_document_content_requires_openknowledge_configured(monkeypatch):
    monkeypatch.setattr(server, "OPENKNOWLEDGE_URL", "")
    client = TestClient(server.app)
    response = client.get("/api/documents/content", params={"path": "x.md"})

    assert response.status_code == 503


def test_health_reports_database_presence(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    db.write_text("")
    monkeypatch.setattr(server, "DATABASE_PATH", str(db))
    client = TestClient(server.app)

    response = client.get("/api/health")

    assert response.json()["database"] is True
