from domain.models.memory import Memory
from domain.models.memory_lifecycle import MemoryLifecycle
from domain.models.scope import MemoryScope
from providers.inmemory.store import (
    InMemoryCheckpointStore,
    InMemoryGraphStore,
    InMemoryKnowledgeStore,
    InMemoryLifecycleStore,
)


def test_knowledge_store_search_excludes_superseded():
    store = InMemoryKnowledgeStore()
    live = store.save(Memory(content="Team uses RabbitMQ"))
    store.save(Memory(content="Team uses Redis", superseded_by=live.memory_id))

    results = store.search("Team uses")
    assert [m.memory_id for m in results] == [live.memory_id]


def test_knowledge_store_get_and_save_round_trip():
    store = InMemoryKnowledgeStore()
    memory = store.save(Memory(content="x"))
    assert store.get(memory.memory_id) is memory
    assert store.get("nonexistent") is None


def test_knowledge_store_list_all_excludes_superseded_and_scopes():
    store = InMemoryKnowledgeStore()
    scope_a = MemoryScope.of(tenant_id="a")
    scope_b = MemoryScope.of(tenant_id="b")
    live = store.save(Memory(scope=scope_a, content="Team uses RabbitMQ"))
    store.save(Memory(scope=scope_a, content="Team uses Redis", superseded_by=live.memory_id))
    store.save(Memory(scope=scope_b, content="unrelated"))

    results = store.list_all(scope=scope_a)

    assert [m.memory_id for m in results] == [live.memory_id]


def test_knowledge_store_list_all_respects_limit():
    store = InMemoryKnowledgeStore()
    for i in range(5):
        store.save(Memory(content=f"fact {i}"))

    assert len(store.list_all(limit=2)) == 2


def test_graph_store_find_related_scoped():
    store = InMemoryGraphStore()
    scope_a = MemoryScope.of(tenant_id="a")
    scope_b = MemoryScope.of(tenant_id="b")
    store.upsert_relationship("Aftermind", "USES", "PostgreSQL", scope=scope_a)
    store.upsert_relationship("Aftermind", "USES", "MongoDB", scope=scope_b)

    assert store.find_related("Aftermind", scope=scope_a) == ["PostgreSQL"]
    assert store.find_related("Aftermind", scope=scope_b) == ["MongoDB"]


def test_checkpoint_store_latest_per_scope():
    store = InMemoryCheckpointStore()
    scope = MemoryScope.of(tenant_id="a")
    from domain.models.checkpoint import Checkpoint

    store.save(Checkpoint(scope=scope, goal="first"))
    second = store.save(Checkpoint(scope=scope, goal="second"))

    assert store.latest(scope) is second
    assert store.latest(MemoryScope.of(tenant_id="b")) is None


def test_lifecycle_store_list_all_scoped():
    store = InMemoryLifecycleStore()
    scope_a = MemoryScope.of(tenant_id="a")
    scope_b = MemoryScope.of(tenant_id="b")
    store.save(MemoryLifecycle(memory_id="m1", scope=scope_a))
    store.save(MemoryLifecycle(memory_id="m2", scope=scope_b))

    assert [r.memory_id for r in store.list_all(scope_a)] == ["m1"]
    assert len(store.list_all()) == 2
