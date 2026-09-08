from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from providers.openknowledge.mapper import build_document, document_from_dict, document_to_dict


def test_build_document_groups_memories_into_sections():
    scope = MemoryScope.of(tenant_id="t1")
    formation_memories = [
        Memory(content="Agent experiences are converted into memory candidates"),
        Memory(content="Candidates are evaluated for usefulness"),
    ]
    graph_memories = [Memory(content="Graphiti sits on Neo4j")]

    document = build_document(
        title="Aftermind Architecture",
        slug="aftermind-architecture",
        sections={"Memory Formation": formation_memories, "Graph Memory": graph_memories},
        scope=scope,
    )

    assert document.title == "Aftermind Architecture"
    assert document.slug == "aftermind-architecture"
    assert document.scope is scope
    assert len(document.sections) == 2
    assert document.sections[0].heading == "Memory Formation"
    assert "Agent experiences are converted into memory candidates." in document.sections[0].body
    assert "Candidates are evaluated for usefulness." in document.sections[0].body
    assert document.sections[1].heading == "Graph Memory"
    assert document.sections[1].body == "Graphiti sits on Neo4j."
    assert set(document.source_memory_ids) == {m.memory_id for m in formation_memories + graph_memories}


def test_build_document_with_no_sections_is_empty():
    document = build_document(title="Empty", slug="empty", sections={})
    assert document.sections == ()
    assert document.source_memory_ids == ()


def test_document_to_dict_and_back_round_trips():
    scope = MemoryScope.of(tenant_id="t1")
    memory = Memory(content="Aftermind is framework-neutral")
    document = build_document(title="Doc", slug="doc", sections={"Overview": [memory]}, scope=scope)

    restored = document_from_dict(document_to_dict(document), scope=scope)

    assert restored.document_id == document.document_id
    assert restored.title == document.title
    assert restored.sections == document.sections
    assert restored.source_memory_ids == document.source_memory_ids
    assert restored.version == document.version
    assert restored.created_at == document.created_at
    assert restored.updated_at == document.updated_at
