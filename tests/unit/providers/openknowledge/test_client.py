from providers.openknowledge.client import LocalMarkdownClient, _safe_slug


def test_write_then_read_round_trips(tmp_path):
    client = LocalMarkdownClient(base_dir=tmp_path)
    data = {"title": "Aftermind Architecture", "sections": [{"heading": "Overview", "body": "text"}]}

    client.write("aftermind-architecture", scope_key="t1", data=data, markdown="# Aftermind Architecture")

    assert client.read("aftermind-architecture", scope_key="t1") == data


def test_write_creates_sibling_markdown_file(tmp_path):
    client = LocalMarkdownClient(base_dir=tmp_path)
    client.write("doc", scope_key="t1", data={"title": "Doc", "sections": []}, markdown="# Doc\n\nbody")

    md_path = tmp_path / "t1" / "doc.md"
    assert md_path.exists()
    assert md_path.read_text() == "# Doc\n\nbody"


def test_read_missing_document_returns_none(tmp_path):
    client = LocalMarkdownClient(base_dir=tmp_path)
    assert client.read("nonexistent", scope_key="t1") is None


def test_search_matches_title_and_body(tmp_path):
    client = LocalMarkdownClient(base_dir=tmp_path)
    client.write(
        "arch",
        scope_key="t1",
        data={"title": "Aftermind Architecture", "sections": [{"heading": "Overview", "body": "uses PostgreSQL"}]},
        markdown="# Aftermind Architecture",
    )
    client.write(
        "unrelated",
        scope_key="t1",
        data={"title": "Unrelated Doc", "sections": [{"heading": "X", "body": "billing invoices"}]},
        markdown="# Unrelated Doc",
    )

    results = client.search("PostgreSQL", scope_key="t1")

    assert len(results) == 1
    assert results[0]["title"] == "Aftermind Architecture"


def test_search_respects_scope_isolation(tmp_path):
    client = LocalMarkdownClient(base_dir=tmp_path)
    client.write("doc", scope_key="t1", data={"title": "T1 Doc", "sections": []}, markdown="# T1 Doc")
    client.write("doc", scope_key="t2", data={"title": "T2 Doc", "sections": []}, markdown="# T2 Doc")

    assert [d["title"] for d in client.search("", scope_key="t1")] == ["T1 Doc"]
    assert [d["title"] for d in client.search("", scope_key="t2")] == ["T2 Doc"]


def test_safe_slug_sanitizes_unsafe_characters():
    assert _safe_slug("Aftermind Architecture!!") == "aftermind-architecture"


def test_safe_slug_empty_falls_back_to_untitled():
    assert _safe_slug("???") == "untitled"
