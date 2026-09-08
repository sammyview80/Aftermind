"""End-to-end test of the memory lifecycle, matching the brief's example:

    Memory A: used 12 times recently -> keep strong
    Memory B: never used for 6 months -> lower priority (decayed)
    Memory C: replaced by a newer fact -> archived

Plus explicit forgetting with provenance cascade — a document and a
successor memory both referencing the forgotten memory lose that
dangling pointer, without losing anything else.
"""
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


def test_strong_stale_and_superseded_memories_diverge_correctly():
    store = FakeLifecycleStore()
    manager = LifecycleManager(store)
    now = datetime.now(timezone.utc)
    six_months_ago = now - timedelta(days=182)

    memory_a = Memory(memory_id="mem_a", content="Client always wants dark themes")
    memory_b = Memory(memory_id="mem_b", content="Client mentioned liking teal once", created_at=six_months_ago)
    memory_c = Memory(memory_id="mem_c", content="Team uses Redis", superseded_by="mem_c2")

    manager.get_or_create(memory_a)
    manager.get_or_create(memory_b)
    manager.get_or_create(memory_c)

    # Memory A: used 12 times recently -> keep strong.
    for _ in range(12):
        manager.record_access("mem_a", at=now)
    lifecycle_a = store.get("mem_a")
    assert lifecycle_a.access_count == 12
    assert lifecycle_a.status == MemoryStatus.ACTIVE
    assert lifecycle_a.importance == 1.0  # capped, clearly "strong"

    # Memory B: never used for 6 months -> lower priority (decayed).
    # Its lifecycle record's clock matches the memory's age.
    store.save(MemoryLifecycle(memory_id="mem_b", created_at=six_months_ago))
    lifecycle_b = manager.run_decay("mem_b", at=now)
    assert lifecycle_b.status == MemoryStatus.DECAYED
    assert lifecycle_b.decay_score > 0.3

    # Memory C: replaced by a newer fact -> archived, not deleted.
    lifecycle_c = manager.archive_superseded(memory_c)
    assert lifecycle_c.status == MemoryStatus.ARCHIVED
    assert lifecycle_c.is_active_for_recall() is False
    assert memory_c.content == "Team uses Redis"  # source memory untouched

    # Recall-eligibility check across all three, matching the example:
    # A strong and eligible, B decayed but still eligible (lower
    # priority, not gone), C excluded from active recall.
    assert store.get("mem_a").is_active_for_recall() is True
    assert store.get("mem_b").is_active_for_recall() is True
    assert store.get("mem_c").is_active_for_recall() is False


def test_forgetting_cascades_provenance_without_deleting_other_records():
    store = FakeLifecycleStore()
    manager = LifecycleManager(store)

    forgotten_memory_id = "mem_x"
    doc = KnowledgeDocument(
        slug="client-prefs",
        title="Client Preferences",
        source_memory_ids=("mem_x", "mem_y"),
    )
    successor = Memory(memory_id="mem_z", content="corrected fact", superseded_by="mem_x")

    lifecycle = manager.forget(forgotten_memory_id, reason="user_requested_deletion")
    assert lifecycle.status == MemoryStatus.FORGOTTEN
    assert lifecycle.is_active_for_recall() is False

    documents, memories = manager.cascade_provenance(forgotten_memory_id, documents=[doc], memories=[successor])

    # Document keeps its other provenance link and all its content —
    # only the dangling pointer to the forgotten memory is gone.
    assert documents[0].source_memory_ids == ("mem_y",)
    assert documents[0].title == "Client Preferences"

    # The successor's dangling superseded_by pointer is cleared, but the
    # successor memory itself is untouched otherwise.
    assert memories[0].superseded_by is None
    assert memories[0].content == "corrected fact"
