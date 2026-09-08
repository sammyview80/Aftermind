from domain.enums.memory_status import MemoryStatus
from domain.models.memory_lifecycle import MemoryLifecycle
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.lifecycle_store import SqliteLifecycleStore


def test_save_then_get_round_trips(tmp_path):
    store = SqliteLifecycleStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    store.save(MemoryLifecycle(memory_id="m1", scope=scope, status=MemoryStatus.DECAYED, access_count=3))

    fetched = store.get("m1")

    assert fetched.status == MemoryStatus.DECAYED
    assert fetched.access_count == 3


def test_save_upserts_on_conflict(tmp_path):
    store = SqliteLifecycleStore(SqliteClient(str(tmp_path / "test.db")))
    store.save(MemoryLifecycle(memory_id="m1", access_count=1))
    store.save(MemoryLifecycle(memory_id="m1", access_count=5))

    assert store.get("m1").access_count == 5


def test_list_all_scoped(tmp_path):
    store = SqliteLifecycleStore(SqliteClient(str(tmp_path / "test.db")))
    scope_a = MemoryScope.of(tenant_id="a")
    scope_b = MemoryScope.of(tenant_id="b")
    store.save(MemoryLifecycle(memory_id="m1", scope=scope_a))
    store.save(MemoryLifecycle(memory_id="m2", scope=scope_b))

    assert [r.memory_id for r in store.list_all(scope_a)] == ["m1"]
    assert len(store.list_all()) == 2


def test_get_missing_returns_none(tmp_path):
    store = SqliteLifecycleStore(SqliteClient(str(tmp_path / "test.db")))
    assert store.get("nonexistent") is None
