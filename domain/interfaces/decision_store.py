from typing import Protocol

from domain.models.memory_decision import MemoryDecision


class DecisionStore(Protocol):
    """Persistence for MemoryDecision — the reconciler's audit trail of
    what it decided and why, kept for provenance even though the
    decision itself isn't read back by the reconciliation logic."""

    def save(self, decision: MemoryDecision) -> MemoryDecision: ...
