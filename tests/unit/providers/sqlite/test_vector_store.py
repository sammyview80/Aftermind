from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.vector_store import SqliteVectorStore


def test_upsert_then_search_similar_ranks_by_cosine_similarity(tmp_path):
    store = SqliteVectorStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")

    store.upsert("a", scope, (1.0, 0.0, 0.0), model="fake")
    store.upsert("b", scope, (0.0, 1.0, 0.0), model="fake")
    store.upsert("c", scope, (0.9, 0.1, 0.0), model="fake")

    results = store.search_similar(scope, (1.0, 0.0, 0.0), limit=5)

    assert [memory_id for memory_id, _ in results][:2] == ["a", "c"]
    assert results[0][1] > 0.99


def test_upsert_is_idempotent_by_memory_id(tmp_path):
    store = SqliteVectorStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")

    store.upsert("a", scope, (1.0, 0.0), model="fake")
    store.upsert("a", scope, (0.0, 1.0), model="fake")

    results = store.search_similar(scope, (0.0, 1.0), limit=5)
    assert results == [("a", 1.0)]


def test_search_similar_scopes_are_isolated(tmp_path):
    store = SqliteVectorStore(SqliteClient(str(tmp_path / "test.db")))
    store.upsert("a", MemoryScope.of(tenant_id="t1"), (1.0, 0.0), model="fake")
    store.upsert("b", MemoryScope.of(tenant_id="t2"), (1.0, 0.0), model="fake")

    results = store.search_similar(MemoryScope.of(tenant_id="t1"), (1.0, 0.0), limit=5)
    assert [memory_id for memory_id, _ in results] == ["a"]


def test_delete_removes_the_embedding(tmp_path):
    store = SqliteVectorStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    store.upsert("a", scope, (1.0, 0.0), model="fake")

    store.delete("a")

    assert store.search_similar(scope, (1.0, 0.0), limit=5) == []
