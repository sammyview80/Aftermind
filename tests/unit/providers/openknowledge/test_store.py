from domain.models.knowledge_document import KnowledgeDocument, KnowledgeSection
from domain.models.scope import MemoryScope
from providers.openknowledge.client import LocalMarkdownClient, _safe_slug
from providers.openknowledge.store import OpenKnowledgeStore


def test_save_then_get_round_trips(tmp_path):
    store = OpenKnowledgeStore(LocalMarkdownClient(base_dir=tmp_path))
    scope = MemoryScope.of(tenant_id="t1")
    document = KnowledgeDocument(
        scope=scope,
        slug="aftermind-architecture",
        title="Aftermind Architecture",
        sections=(KnowledgeSection(heading="Overview", body="Aftermind is framework-neutral."),),
    )

    saved = store.save(document)
    fetched = store.get("aftermind-architecture", scope=scope)

    assert fetched.title == "Aftermind Architecture"
    assert fetched.sections == document.sections
    assert saved.version == 1


def test_save_increments_version_on_existing_slug(tmp_path):
    store = OpenKnowledgeStore(LocalMarkdownClient(base_dir=tmp_path))
    scope = MemoryScope.of(tenant_id="t1")

    first = store.save(KnowledgeDocument(scope=scope, slug="doc", title="v1", sections=()))
    second = store.save(KnowledgeDocument(scope=scope, slug="doc", title="v2", sections=()))

    assert first.version == 1
    assert second.version == 2
    assert store.get("doc", scope=scope).title == "v2"


def test_save_writes_a_readable_markdown_file(tmp_path):
    store = OpenKnowledgeStore(LocalMarkdownClient(base_dir=tmp_path))
    scope = MemoryScope.of(tenant_id="t1")
    document = KnowledgeDocument(
        scope=scope,
        slug="doc",
        title="Aftermind Architecture",
        sections=(KnowledgeSection(heading="Memory Formation", body="Candidates are evaluated for usefulness."),),
    )

    store.save(document)

    md_path = tmp_path / _safe_slug(scope.key()) / "doc.md"
    content = md_path.read_text()
    assert "# Aftermind Architecture" in content
    assert "## Memory Formation" in content
    assert "Candidates are evaluated for usefulness." in content


def test_get_missing_document_returns_none(tmp_path):
    store = OpenKnowledgeStore(LocalMarkdownClient(base_dir=tmp_path))
    assert store.get("nonexistent") is None


def test_search_returns_matching_documents(tmp_path):
    store = OpenKnowledgeStore(LocalMarkdownClient(base_dir=tmp_path))
    scope = MemoryScope.of(tenant_id="t1")
    store.save(
        KnowledgeDocument(
            scope=scope, slug="arch", title="Aftermind Architecture",
            sections=(KnowledgeSection(heading="Graph Memory", body="Graphiti sits on Neo4j."),),
        )
    )

    results = store.search("Neo4j", scope=scope)

    assert len(results) == 1
    assert results[0].title == "Aftermind Architecture"
