from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from dataclasses import replace

from core.preferences.reconciler import LLMPreferenceReconciler
from core.preferences.signals import extract_signals
from domain.enums.preference_source import PreferenceSource
from domain.interfaces.preference_evidence_store import PreferenceEvidenceStore
from domain.interfaces.preference_store import PreferenceStore
from domain.models.preference import Preference
from domain.models.scope import MemoryScope

# How many buffered turns of raw text accumulate before the (comparatively
# expensive) LLM reconciler runs looking for subtler patterns — not on
# every turn, since that would be an LLM call per message for something
# this low-stakes.
DEFAULT_EVIDENCE_THRESHOLD = 5

# Evidence weight per observation: an explicit instruction ("keep this
# short") counts for as much as several repeated behavioral observations
# at once, so it doesn't take 8 more turns to reach the same confidence
# a single direct statement should already earn.
_EXPLICIT_EVIDENCE_WEIGHT = 8
_BEHAVIORAL_EVIDENCE_WEIGHT = 1

# confidence = evidence_count / (evidence_count + _HALF_LIFE) is a simple
# saturating curve: 1 observation -> ~0.25, 5 -> ~0.625, 20 -> ~0.87,
# asymptotic toward 1 but capped below it so nothing is ever "certain".
_HALF_LIFE = 3.0
_MAX_CONFIDENCE = 0.95
# Explicit instructions are trusted immediately, not just weighted higher.
_MIN_EXPLICIT_CONFIDENCE = 0.9


def _confidence(evidence_count: int, explicit: bool) -> float:
    curve = min(_MAX_CONFIDENCE, evidence_count / (evidence_count + _HALF_LIFE))
    return max(curve, _MIN_EXPLICIT_CONFIDENCE) if explicit else curve


class PreferenceManager:
    """Reconciles observed behavior/preference signals into one stable,
    evidence-weighted profile per (scope, dimension) — the gradual
    "observe -> extract signal -> compare -> ignore/update/supersede"
    pipeline, mirroring how `Reconciler` handles factual memories but
    kept deliberately simpler: a preference profile has one active
    value per dimension, not an evidence graph.
    """

    def __init__(
        self,
        store: PreferenceStore,
        evidence_store: Optional[PreferenceEvidenceStore] = None,
        reconciler: Optional[LLMPreferenceReconciler] = None,
        evidence_threshold: int = DEFAULT_EVIDENCE_THRESHOLD,
    ) -> None:
        self._store = store
        self._evidence_store = evidence_store
        self._reconciler = reconciler
        self._evidence_threshold = evidence_threshold

    def observe(
        self,
        scope: Optional[MemoryScope],
        dimension: str,
        value: Mapping[str, Any],
        explicit: bool = False,
    ) -> Preference:
        """Record one observation of `value` for `dimension`. Reconciles
        against whatever is currently active for that dimension:
          - nothing active yet -> create.
          - same value observed again -> reinforce in place (evidence_count
            and confidence go up; the row is *updated*, not duplicated).
          - a different value observed -> supersede: a new row becomes the
            active preference for the dimension, the old one is chained
            via `superseded_by` (same pattern as `Memory`), so a
            preference profile can visibly evolve (e.g. verbosity=short
            superseded by verbosity=adaptive after enough contrary
            evidence) instead of flip-flopping silently.
        """
        scope = scope.stable() if scope is not None else None
        value = dict(value)
        source = PreferenceSource.EXPLICIT if explicit else PreferenceSource.REPEATED
        weight = _EXPLICIT_EVIDENCE_WEIGHT if explicit else _BEHAVIORAL_EVIDENCE_WEIGHT

        previous = self._store.latest_by_dimension(scope, dimension)
        now = datetime.now(timezone.utc)

        if previous is None:
            preference = Preference(
                scope=scope,
                dimension=dimension,
                value=value,
                confidence=_confidence(weight, explicit),
                evidence_count=weight,
                source=source if explicit else PreferenceSource.INFERRED,
                version=1,
                created_at=now,
                updated_at=now,
            )
            return self._store.save(preference)

        if dict(previous.value) == value:
            evidence_count = previous.evidence_count + weight
            updated = replace(
                previous,
                confidence=_confidence(evidence_count, explicit or previous.source == PreferenceSource.EXPLICIT),
                evidence_count=evidence_count,
                source=source if explicit else previous.source,
                updated_at=now,
            )
            return self._store.save(updated)

        successor = Preference(
            scope=scope,
            dimension=dimension,
            value=value,
            confidence=_confidence(weight, explicit),
            evidence_count=weight,
            source=source if explicit else PreferenceSource.INFERRED,
            version=previous.version + 1,
            created_at=now,
            updated_at=now,
        )
        self._store.save(successor)
        self._store.save(replace(previous, superseded_by=successor.preference_id, updated_at=now))
        return successor

    def profile(self, scope: Optional[MemoryScope]) -> tuple[Preference, ...]:
        """Every currently active preference in scope — the stable
        profile recall injects into context."""
        return self._store.list_active(scope.stable() if scope is not None else None)

    def observe_text(self, scope: Optional[MemoryScope], text: str) -> tuple[Preference, ...]:
        """Two-stage learning for one turn of raw text:

        1. Cheap heuristic signals (`core/preferences/signals.py`) apply
           immediately — a direct instruction like "keep it short" earns
           high confidence right away, no need to wait for anything.
        2. The raw text always joins a durable evidence buffer regardless
           of whether a heuristic matched. Once enough has accumulated,
           the LLM reconciler reads it all against the current profile
           looking for subtler patterns ("what next?" three times in a
           row, never wanting a preamble) that no single-message regex
           could catch, and the buffer is cleared either way — an
           `ignore` verdict still consumes the evidence that produced it,
           so a handful of ambiguous messages don't linger forever
           waiting to combine with unrelated later ones.

        Returns whatever preferences changed as a result of this call
        (heuristic hits, plus any LLM-driven updates when the buffer
        happened to flush)."""
        scope = scope.stable() if scope is not None else None
        text = (text or "").strip()

        changed = [
            self.observe(scope, signal.dimension, signal.value, explicit=signal.explicit)
            for signal in extract_signals(text)
        ]

        if self._evidence_store is None or not text:
            return tuple(changed)

        self._evidence_store.append(scope, text)
        evidence = self._evidence_store.recent(scope)
        if self._reconciler is None or len(evidence) < self._evidence_threshold:
            return tuple(changed)

        result = self._reconciler.reconcile(self.profile(scope), evidence)
        self._evidence_store.clear(scope)
        if result.action == "update":
            changed.extend(
                self.observe(scope, dimension, value, explicit=True) for dimension, value in result.preferences.items()
            )
        return tuple(changed)
