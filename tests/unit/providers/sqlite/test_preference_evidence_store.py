from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.preference_evidence_store import SqlitePreferenceEvidenceStore


def test_append_then_recent_round_trips_in_order(tmp_path):
    store = SqlitePreferenceEvidenceStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")

    store.append(scope, "keep it short")
    store.append(scope, "what next?")

    assert store.recent(scope) == ("keep it short", "what next?")


def test_clear_removes_all_evidence_for_scope(tmp_path):
    store = SqlitePreferenceEvidenceStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    store.append(scope, "keep it short")

    store.clear(scope)

    assert store.recent(scope) == ()


def test_scopes_are_isolated(tmp_path):
    store = SqlitePreferenceEvidenceStore(SqliteClient(str(tmp_path / "test.db")))
    store.append(MemoryScope.of(tenant_id="t1"), "for t1")
    store.append(MemoryScope.of(tenant_id="t2"), "for t2")

    assert store.recent(MemoryScope.of(tenant_id="t1")) == ("for t1",)
