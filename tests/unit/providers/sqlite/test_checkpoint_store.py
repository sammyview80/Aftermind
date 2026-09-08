from domain.models.checkpoint import Checkpoint
from domain.models.scope import MemoryScope
from providers.sqlite.checkpoint_store import SqliteCheckpointStore
from providers.sqlite.client import SqliteClient


def test_save_then_latest_round_trips(tmp_path):
    store = SqliteCheckpointStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    checkpoint = store.save(Checkpoint(scope=scope, goal="Build login flow", version=1))

    latest = store.latest(scope)

    assert latest.checkpoint_id == checkpoint.checkpoint_id
    assert latest.goal == "Build login flow"


def test_latest_returns_highest_version(tmp_path):
    store = SqliteCheckpointStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    store.save(Checkpoint(scope=scope, goal="first", version=1))
    second = store.save(Checkpoint(scope=scope, goal="second", version=2))

    assert store.latest(scope).checkpoint_id == second.checkpoint_id


def test_survives_reopening_the_same_file(tmp_path):
    db_path = str(tmp_path / "test.db")
    scope = MemoryScope.of(tenant_id="t1")
    SqliteCheckpointStore(SqliteClient(db_path)).save(Checkpoint(scope=scope, goal="Build login flow"))

    reopened = SqliteCheckpointStore(SqliteClient(db_path))
    assert reopened.latest(scope).goal == "Build login flow"


def test_latest_returns_none_for_unknown_scope(tmp_path):
    store = SqliteCheckpointStore(SqliteClient(str(tmp_path / "test.db")))
    assert store.latest(MemoryScope.of(tenant_id="nonexistent")) is None
