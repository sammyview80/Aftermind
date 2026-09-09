from domain.enums.preference_source import PreferenceSource
from domain.models.preference import Preference
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.preference_store import SqlitePreferenceStore


def test_save_then_latest_by_dimension_round_trips(tmp_path):
    store = SqlitePreferenceStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    pref = store.save(
        Preference(
            scope=scope,
            dimension="response_style.verbosity",
            value={"verbosity": "short"},
            confidence=0.9,
            evidence_count=8,
            source=PreferenceSource.EXPLICIT,
        )
    )

    latest = store.latest_by_dimension(scope, "response_style.verbosity")

    assert latest.preference_id == pref.preference_id
    assert latest.value == {"verbosity": "short"}
    assert latest.source == PreferenceSource.EXPLICIT


def test_save_upserts_the_same_row_by_preference_id(tmp_path):
    store = SqlitePreferenceStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    pref = store.save(
        Preference(scope=scope, dimension="response_style.verbosity", value={"verbosity": "short"}, evidence_count=1)
    )
    from dataclasses import replace

    store.save(replace(pref, evidence_count=5, confidence=0.6))

    latest = store.latest_by_dimension(scope, "response_style.verbosity")
    assert latest.preference_id == pref.preference_id
    assert latest.evidence_count == 5


def test_superseded_preference_is_excluded_from_latest_and_list_active(tmp_path):
    store = SqlitePreferenceStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    old = store.save(
        Preference(scope=scope, dimension="response_style.verbosity", value={"verbosity": "short"}, version=1)
    )
    new = store.save(
        Preference(scope=scope, dimension="response_style.verbosity", value={"verbosity": "detailed"}, version=2)
    )
    from dataclasses import replace

    store.save(replace(old, superseded_by=new.preference_id))

    assert store.latest_by_dimension(scope, "response_style.verbosity").preference_id == new.preference_id
    active = store.list_active(scope)
    assert len(active) == 1
    assert active[0].preference_id == new.preference_id


def test_list_active_returns_one_row_per_dimension(tmp_path):
    store = SqlitePreferenceStore(SqliteClient(str(tmp_path / "test.db")))
    scope = MemoryScope.of(tenant_id="t1")
    store.save(Preference(scope=scope, dimension="response_style.verbosity", value={"verbosity": "short"}))
    store.save(Preference(scope=scope, dimension="response_style.structure", value={"structure": "stepwise"}))

    assert len(store.list_active(scope)) == 2
