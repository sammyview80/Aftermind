from typing import Optional

from core.preferences.manager import PreferenceManager
from core.preferences.reconciler import PreferenceReconciliation
from domain.enums.preference_source import PreferenceSource
from domain.models.preference import Preference
from domain.models.scope import MemoryScope


def _key(scope: Optional[MemoryScope]) -> str:
    return scope.key() if scope is not None else "*"


class FakePreferenceEvidenceStore:
    def __init__(self) -> None:
        self._by_scope: dict[str, list[str]] = {}

    def append(self, scope: Optional[MemoryScope], text: str) -> None:
        self._by_scope.setdefault(_key(scope), []).append(text)

    def recent(self, scope: Optional[MemoryScope]) -> tuple[str, ...]:
        return tuple(self._by_scope.get(_key(scope), ()))

    def clear(self, scope: Optional[MemoryScope]) -> None:
        self._by_scope.pop(_key(scope), None)


class FakeReconciler:
    def __init__(self, result: PreferenceReconciliation) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def reconcile(self, profile, evidence):
        self.calls.append((profile, evidence))
        return self.result


class FakePreferenceStore:
    def __init__(self) -> None:
        self._preferences: dict[str, Preference] = {}

    def save(self, preference: Preference) -> Preference:
        self._preferences[preference.preference_id] = preference
        return preference

    def latest_by_dimension(self, scope: Optional[MemoryScope], dimension: str) -> Optional[Preference]:
        matches = [
            p
            for p in self._preferences.values()
            if p.scope == scope and p.dimension == dimension and p.superseded_by is None
        ]
        return max(matches, key=lambda p: p.version) if matches else None

    def list_active(self, scope: Optional[MemoryScope]) -> tuple[Preference, ...]:
        return tuple(p for p in self._preferences.values() if p.scope == scope and p.superseded_by is None)


def test_observe_creates_a_new_preference():
    manager = PreferenceManager(FakePreferenceStore())
    scope = MemoryScope.of(tenant_id="t1")

    pref = manager.observe(scope, "response_style.verbosity", {"verbosity": "short"}, explicit=True)

    assert pref.value == {"verbosity": "short"}
    assert pref.confidence >= 0.9
    assert pref.evidence_count == 8


def test_explicit_instruction_reaches_high_confidence_immediately():
    manager = PreferenceManager(FakePreferenceStore())
    scope = MemoryScope.of(tenant_id="t1")

    pref = manager.observe(scope, "response_style.verbosity", {"verbosity": "short"}, explicit=True)

    assert pref.source == PreferenceSource.EXPLICIT
    assert pref.confidence >= 0.9


def test_single_inferred_observation_stays_a_weak_signal():
    manager = PreferenceManager(FakePreferenceStore())
    scope = MemoryScope.of(tenant_id="t1")

    pref = manager.observe(scope, "response_style.verbosity", {"verbosity": "short"}, explicit=False)

    assert pref.confidence < 0.5
    assert pref.evidence_count == 1


def test_repeated_same_value_reinforces_in_place_not_as_new_rows():
    store = FakePreferenceStore()
    manager = PreferenceManager(store)
    scope = MemoryScope.of(tenant_id="t1")

    for _ in range(5):
        manager.observe(scope, "response_style.verbosity", {"verbosity": "short"}, explicit=False)

    profile = manager.profile(scope)
    assert len(profile) == 1
    assert profile[0].evidence_count == 5
    assert profile[0].confidence > 0.5


def test_contradicting_value_supersedes_previous_preference():
    store = FakePreferenceStore()
    manager = PreferenceManager(store)
    scope = MemoryScope.of(tenant_id="t1")

    first = manager.observe(scope, "response_style.verbosity", {"verbosity": "short"}, explicit=True)
    second = manager.observe(scope, "response_style.verbosity", {"verbosity": "detailed"}, explicit=True)

    profile = manager.profile(scope)
    assert len(profile) == 1
    assert profile[0].preference_id == second.preference_id
    assert profile[0].value == {"verbosity": "detailed"}
    assert second.version == first.version + 1


def test_profile_only_returns_active_preferences_for_the_scope():
    manager = PreferenceManager(FakePreferenceStore())
    scope_a = MemoryScope.of(tenant_id="t1")
    scope_b = MemoryScope.of(tenant_id="t2")

    manager.observe(scope_a, "response_style.verbosity", {"verbosity": "short"}, explicit=True)
    manager.observe(scope_b, "response_style.structure", {"structure": "stepwise"}, explicit=True)

    assert len(manager.profile(scope_a)) == 1
    assert manager.profile(scope_a)[0].dimension == "response_style.verbosity"


def test_observe_text_applies_heuristic_signal_immediately():
    manager = PreferenceManager(FakePreferenceStore())
    scope = MemoryScope.of(tenant_id="t1")

    changed = manager.observe_text(scope, "keep it short")

    assert any(p.value == {"verbosity": "short"} for p in changed)
    assert manager.profile(scope)


def test_observe_text_buffers_evidence_without_a_reconciler():
    evidence_store = FakePreferenceEvidenceStore()
    manager = PreferenceManager(FakePreferenceStore(), evidence_store=evidence_store)
    scope = MemoryScope.of(tenant_id="t1")

    manager.observe_text(scope, "hello there")

    assert evidence_store.recent(scope.stable()) == ("hello there",)
    assert manager.profile(scope) == ()


def test_observe_text_does_not_call_reconciler_below_threshold():
    evidence_store = FakePreferenceEvidenceStore()
    reconciler = FakeReconciler(PreferenceReconciliation("ignore", {}, 0.0, ""))
    manager = PreferenceManager(
        FakePreferenceStore(), evidence_store=evidence_store, reconciler=reconciler, evidence_threshold=3
    )
    scope = MemoryScope.of(tenant_id="t1")

    manager.observe_text(scope, "msg one")
    manager.observe_text(scope, "msg two")

    assert reconciler.calls == []


def test_observe_text_triggers_reconciler_at_threshold_and_clears_buffer():
    evidence_store = FakePreferenceEvidenceStore()
    reconciler = FakeReconciler(
        PreferenceReconciliation("update", {"response_style.directness": {"directness": "high"}}, 0.85, "pattern")
    )
    manager = PreferenceManager(
        FakePreferenceStore(), evidence_store=evidence_store, reconciler=reconciler, evidence_threshold=3
    )
    scope = MemoryScope.of(tenant_id="t1")

    manager.observe_text(scope, "what next?")
    manager.observe_text(scope, "what next?")
    changed = manager.observe_text(scope, "what next?")

    assert len(reconciler.calls) == 1
    assert evidence_store.recent(scope.stable()) == ()
    profile = manager.profile(scope)
    assert any(p.dimension == "response_style.directness" and p.value == {"directness": "high"} for p in profile)
    assert changed


def test_observe_text_ignore_verdict_still_clears_the_buffer():
    evidence_store = FakePreferenceEvidenceStore()
    reconciler = FakeReconciler(PreferenceReconciliation("ignore", {}, 0.1, "no pattern"))
    manager = PreferenceManager(
        FakePreferenceStore(), evidence_store=evidence_store, reconciler=reconciler, evidence_threshold=2
    )
    scope = MemoryScope.of(tenant_id="t1")

    manager.observe_text(scope, "hi")
    manager.observe_text(scope, "thanks")

    assert evidence_store.recent(scope.stable()) == ()
    assert manager.profile(scope) == ()
