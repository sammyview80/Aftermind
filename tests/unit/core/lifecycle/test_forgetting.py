from core.lifecycle.forgetting import cascade_forget_documents, cascade_forget_memories, forget
from domain.enums.memory_status import MemoryStatus
from domain.models.knowledge_document import KnowledgeDocument
from domain.models.memory import Memory
from domain.models.memory_lifecycle import MemoryLifecycle


def test_forget_sets_terminal_status_and_reason():
    lifecycle = MemoryLifecycle(memory_id="m1")
    forgotten = forget(lifecycle, reason="user_requested")

    assert forgotten.status == MemoryStatus.FORGOTTEN
    assert forgotten.metadata["forgotten_reason"] == "user_requested"
    assert "forgotten_at" in forgotten.metadata


def test_cascade_forget_documents_strips_id_but_keeps_document():
    doc = KnowledgeDocument(slug="doc", title="Doc", source_memory_ids=("m1", "m2"))
    unrelated = KnowledgeDocument(slug="other", title="Other", source_memory_ids=("m3",))

    updated = cascade_forget_documents("m1", [doc, unrelated])

    assert updated[0].source_memory_ids == ("m2",)
    assert updated[0].slug == "doc"
    assert updated[0].title == "Doc"
    assert updated[1] is unrelated  # untouched, no dangling reference


def test_cascade_forget_memories_clears_dangling_superseded_by():
    superseding = Memory(memory_id="m2", content="new fact")
    other = Memory(memory_id="m3", content="unrelated", superseded_by="m4")

    updated = cascade_forget_memories("m2", [Memory(memory_id="m1", content="old fact", superseded_by="m2"), other])

    assert updated[0].superseded_by is None
    assert updated[1] is other  # unrelated pointer untouched
