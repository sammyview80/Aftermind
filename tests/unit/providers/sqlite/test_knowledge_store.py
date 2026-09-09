from domain.enums.memory_domain import MemoryDomain
from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.knowledge_store import SqliteKnowledgeStore


def test_save_then_get_round_trips(tmp_path):
    store = SqliteKnowledgeStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    memory = store.save(Memory(scope=scope, content="Team uses PostgreSQL", entities=["team", "postgresql"]))

    fetched = store.get(memory.memory_id)

    assert fetched.content == "Team uses PostgreSQL"
    assert fetched.entities == ("team", "postgresql")
    assert fetched.scope.get("tenant_id") == "t1"
    assert fetched.memory_domain == MemoryDomain.PROJECT


def test_save_then_get_round_trips_a_non_default_memory_domain(tmp_path):
    store = SqliteKnowledgeStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    memory = store.save(Memory(scope=scope, content="Current blocker is a failing build", memory_domain=MemoryDomain.SESSION))

    assert store.get(memory.memory_id).memory_domain == MemoryDomain.SESSION


def test_search_excludes_superseded_and_scopes_correctly(tmp_path):
    store = SqliteKnowledgeStore(SqliteClient(str(tmp_path / "test.db")))
    scope_a = MemoryScope.of(tenant_id="a")
    scope_b = MemoryScope.of(tenant_id="b")

    live = store.save(Memory(scope=scope_a, content="Team uses RabbitMQ"))
    store.save(Memory(scope=scope_a, content="Team uses Redis", superseded_by=live.memory_id))
    store.save(Memory(scope=scope_b, content="Team uses RabbitMQ"))

    results = store.search("Team uses", scope=scope_a)
    assert [m.memory_id for m in results] == [live.memory_id]


def test_survives_reopening_the_same_file(tmp_path):
    db_path = str(tmp_path / "test.db")
    scope = MemoryScope.of(tenant_id="t1")

    first_store = SqliteKnowledgeStore(SqliteClient(db_path))
    memory = first_store.save(Memory(scope=scope, content="Aftermind uses an LLM-powered Memory Reconciler"))

    # Simulate a process restart: brand-new client/store over the same file.
    second_store = SqliteKnowledgeStore(SqliteClient(db_path))
    fetched = second_store.get(memory.memory_id)

    assert fetched is not None
    assert fetched.content == "Aftermind uses an LLM-powered Memory Reconciler"


def test_save_updates_existing_memory_on_conflict(tmp_path):
    store = SqliteKnowledgeStore(SqliteClient(str(tmp_path / "test.db")))
    from dataclasses import replace

    memory = store.save(Memory(content="v1"))
    store.save(replace(memory, content="v2", version=2))

    assert store.get(memory.memory_id).content == "v2"


def test_list_all_excludes_superseded_and_scopes(tmp_path):
    store = SqliteKnowledgeStore(SqliteClient(str(tmp_path / "test.db")))
    scope_a = MemoryScope.of(tenant_id="a")
    scope_b = MemoryScope.of(tenant_id="b")
    live = store.save(Memory(scope=scope_a, content="Team uses RabbitMQ"))
    store.save(Memory(scope=scope_a, content="Team uses Redis", superseded_by=live.memory_id))
    store.save(Memory(scope=scope_b, content="unrelated"))

    results = store.list_all(scope=scope_a)

    assert [m.memory_id for m in results] == [live.memory_id]


def test_list_all_respects_limit(tmp_path):
    store = SqliteKnowledgeStore(SqliteClient(str(tmp_path / "test.db")))
    for i in range(5):
        store.save(Memory(content=f"fact {i}"))

    assert len(store.list_all(limit=2)) == 2
