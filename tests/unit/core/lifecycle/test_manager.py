from datetime import datetime, timedelta, timezone
from typing import Optional

from core.lifecycle.manager import LifecycleManager
from domain.enums.memory_status import MemoryStatus
from domain.models.knowledge_document import KnowledgeDocument
from domain.models.memory import Memory
from domain.models.memory_lifecycle import MemoryLifecycle
from domain.models.scope import MemoryScope


class FakeLifecycleStore:
    def __init__(self) -> None:
        self._records: dict[str, MemoryLifecycle] = {}

    def get(self, memory_id: str, scope: Optional[MemoryScope] = None) -> Optional[MemoryLifecycle]:
        return self._records.get(memory_id)

    def save(self, lifecycle: MemoryLifecycle) -> MemoryLifecycle:
        self._records[lifecycle.memory_id] = lifecycle
        return lifecycle

    def list_all(self, scope: Optional[MemoryScope] = None) -> list[MemoryLifecycle]:
        return list(self._records.values())


def test_get_or_create_creates_once():
    store = FakeLifecycleStore()
    manager = LifecycleManager(store)
    memory = Memory(memory_id="m1", content="x")

    first = manager.get_or_create(memory)
    second = manager.get_or_create(memory)

    assert first.memory_id == "m1"
    assert second is first


def test_record_access_reinforces_and_persists():
    store = FakeLifecycleStore()
    manager = LifecycleManager(store)

    result = manager.record_access("m1")

    assert result.access_count == 1
    assert store.get("m1").access_count == 1


def test_run_decay_returns_none_for_unknown_memory():
    manager = LifecycleManager(FakeLifecycleStore())
    assert manager.run_decay("nonexistent") is None


def test_run_decay_updates_existing_record():
    store = FakeLifecycleStore()
    store.save(MemoryLifecycle(memory_id="m1", created_at=datetime.now(timezone.utc) - timedelta(days=2000)))
    manager = LifecycleManager(store)

    result = manager.run_decay("m1")

    assert result.status == MemoryStatus.EXPIRED


def test_sweep_decay_applies_to_every_record_in_scope():
    store = FakeLifecycleStore()
    old = datetime.now(timezone.utc) - timedelta(days=2000)
    store.save(MemoryLifecycle(memory_id="m1", created_at=old))
    store.save(MemoryLifecycle(memory_id="m2", created_at=old))
    manager = LifecycleManager(store)

    results = manager.sweep_decay()

    assert len(results) == 2
    assert all(r.status == MemoryStatus.EXPIRED for r in results)


def test_archive_superseded_archives_only_when_superseded():
    store = FakeLifecycleStore()
    manager = LifecycleManager(store)

    not_superseded = Memory(memory_id="m1", content="x")
    assert manager.archive_superseded(not_superseded) is None

    superseded = Memory(memory_id="m2", content="old", superseded_by="m3")
    result = manager.archive_superseded(superseded)
    assert result.status == MemoryStatus.ARCHIVED
    assert "m3" in result.metadata["archived_reason"]


def test_forget_sets_terminal_status_and_persists():
    store = FakeLifecycleStore()
    manager = LifecycleManager(store)

    result = manager.forget("m1", reason="user_requested")

    assert result.status == MemoryStatus.FORGOTTEN
    assert store.get("m1").status == MemoryStatus.FORGOTTEN


def test_cascade_provenance_cleans_documents_and_memories():
    manager = LifecycleManager(FakeLifecycleStore())
    doc = KnowledgeDocument(slug="doc", title="Doc", source_memory_ids=("m1", "m2"))
    memory = Memory(memory_id="m3", content="old", superseded_by="m1")

    documents, memories = manager.cascade_provenance("m1", documents=[doc], memories=[memory])

    assert documents[0].source_memory_ids == ("m2",)
    assert memories[0].superseded_by is None
