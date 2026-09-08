"""End-to-end test of the OpenKnowledge layer:

    Raw StoredMemory -> (curated selection, not "every memory") ->
    build_document (mapper.py) -> OpenKnowledgeStore -> durable markdown

This is deliberately NOT wired to receive every Memory a Reconciler
produces — the caller (eventually the Consolidation Engine) decides
which memories are consolidated/durable enough to belong in a document.
This test plays that curation role by hand, matching the example in the
brief: episodic/noisy content never reaches OpenKnowledge at all.
"""
from domain.enums.memory_type import MemoryType
from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from providers.openknowledge.client import LocalMarkdownClient
from providers.openknowledge.mapper import build_document
from providers.openknowledge.store import OpenKnowledgeStore


def test_consolidated_memories_produce_readable_architecture_doc(tmp_path):
    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    store = OpenKnowledgeStore(LocalMarkdownClient(base_dir=tmp_path))

    formation_memories = [
        Memory(scope=scope, content="Agent experiences are converted into memory candidates, evaluated for usefulness, and reconciled against existing knowledge using an LLM-powered Memory Reconciler", memory_type=MemoryType.SEMANTIC),
    ]
    graph_memories = [
        Memory(scope=scope, content="Graphiti with Neo4j handles entities, relationships, and temporal graph knowledge", memory_type=MemoryType.SEMANTIC),
    ]
    # Episodic noise that should NEVER reach OpenKnowledge — this test
    # never passes it to build_document, proving the "only curated
    # sections" rule by simply not routing it through.
    episodic_noise = Memory(scope=scope, content="Ran repo_search tool at 03:14 UTC", memory_type=MemoryType.EPISODIC)

    document = build_document(
        title="Aftermind Architecture",
        slug="aftermind-architecture",
        sections={
            "Memory Formation": formation_memories,
            "Graph Memory": graph_memories,
        },
        scope=scope,
    )
    saved = store.save(document)

    fetched = store.get("aftermind-architecture", scope=scope)
    markdown = fetched.to_markdown()

    assert markdown.startswith("# Aftermind Architecture")
    assert "## Memory Formation" in markdown
    assert "## Graph Memory" in markdown
    assert "LLM-powered Memory Reconciler" in markdown
    assert "Graphiti with Neo4j" in markdown

    # The episodic memory was never given to build_document, so it can't
    # have leaked into the document by any path.
    assert episodic_noise.content not in markdown
    assert episodic_noise.memory_id not in fetched.source_memory_ids

    assert saved.version == 1
    assert set(fetched.source_memory_ids) == {m.memory_id for m in formation_memories + graph_memories}


def test_updating_a_document_with_a_new_section_increments_version(tmp_path):
    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    store = OpenKnowledgeStore(LocalMarkdownClient(base_dir=tmp_path))

    first_pass = build_document(
        title="Aftermind Architecture",
        slug="aftermind-architecture",
        sections={"Memory Formation": [Memory(scope=scope, content="Candidates are evaluated for usefulness")]},
        scope=scope,
    )
    store.save(first_pass)

    second_pass = build_document(
        title="Aftermind Architecture",
        slug="aftermind-architecture",
        sections={
            "Memory Formation": [Memory(scope=scope, content="Candidates are evaluated for usefulness")],
            "Graph Memory": [Memory(scope=scope, content="Graphiti sits on Neo4j")],
        },
        scope=scope,
    )
    updated = store.save(second_pass)

    assert updated.version == 2
    fetched = store.get("aftermind-architecture", scope=scope)
    assert "## Graph Memory" in fetched.to_markdown()
