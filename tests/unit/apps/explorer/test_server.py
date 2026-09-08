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


def _seed_memories(db_path, n):
    import sqlite3
    from datetime import datetime, timezone

    con = sqlite3.connect(db_path)
    con.execute(
        "CREATE TABLE memories (memory_id TEXT PRIMARY KEY, scope_key TEXT, scope_levels TEXT, content TEXT, "
        "memory_type TEXT, entities TEXT, relationships TEXT, confidence REAL, version INTEGER, "
        "superseded_by TEXT, source_candidate_ids TEXT, metadata TEXT, created_at TEXT, updated_at TEXT)"
    )
    con.execute("CREATE TABLE lifecycle (memory_id TEXT PRIMARY KEY, status TEXT, access_count INTEGER, "
                "importance REAL, decay_score REAL, last_accessed_at TEXT)")
    now = datetime.now(timezone.utc).isoformat()
    for i in range(n):
        con.execute(
            "INSERT INTO memories VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"m{i}", "scope-a", "{}", f"fact number {i}", "semantic", "[]", "[]", 0.9, 1, None, "[]", "{}", now, now),
        )
    con.commit()
    con.close()


def test_memories_pagination_returns_correct_page_and_totals(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    _seed_memories(str(db), 7)
    monkeypatch.setattr(server, "DATABASE_PATH", str(db))
    client = TestClient(server.app)

    page1 = client.get("/api/memories", params={"page": 1, "page_size": 3}).json()
    page3 = client.get("/api/memories", params={"page": 3, "page_size": 3}).json()

    assert page1["total"] == 7
    assert page1["total_pages"] == 3
    assert len(page1["memories"]) == 3
    assert len(page3["memories"]) == 1  # last page, partial


def test_memories_search_filter_narrows_results(tmp_path, monkeypatch):
    db = tmp_path / "t.db"
    _seed_memories(str(db), 5)
    monkeypatch.setattr(server, "DATABASE_PATH", str(db))
    client = TestClient(server.app)

    result = client.get("/api/memories", params={"search": "number 3"}).json()

    assert result["total"] == 1
    assert "number 3" in result["memories"][0]["content"]


def test_parse_scope_key_extracts_session_id_by_hierarchy_position():
    levels = server._parse_scope_key("default:*:proj:*:*:*:*:*:sess123:*")
    assert levels["project_id"] == "proj"
    assert levels["session_id"] == "sess123"
    assert levels["run_id"] is None


def test_parse_scope_key_handles_empty_string():
    assert server._parse_scope_key("") == {name: None for name in server._HIERARCHY}


def test_health_reports_database_presence(tmp_path, monkeypatch):
    db = tmp_path / "test.db"
    db.write_text("")
    monkeypatch.setattr(server, "DATABASE_PATH", str(db))
    client = TestClient(server.app)

    response = client.get("/api/health")

    assert response.json()["database"] is True
