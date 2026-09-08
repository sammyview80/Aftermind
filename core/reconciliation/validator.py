from dataclasses import replace

from domain.enums.reconciliation_action import ReconciliationAction
from domain.models.candidate import Candidate
from domain.models.memory import Memory
from domain.models.memory_decision import MemoryDecision

_TARGET_REQUIRED_ACTIONS = frozenset(
    {ReconciliationAction.UPDATE, ReconciliationAction.MERGE, ReconciliationAction.SUPERSEDE}
)

DEFAULT_MIN_CONFIDENCE = 0.3


class Validator:
    """Sanity-checks a reconciliation decision before it is applied.

    Guards against a reconciler producing a decision that isn't
    internally consistent — e.g. UPDATE with no target, or a target that
    wasn't actually in the retrieved evidence — by downgrading it to a
    safe fallback rather than applying it as-is.
    """

    def __init__(self, min_confidence: float = DEFAULT_MIN_CONFIDENCE) -> None:
        self.min_confidence = min_confidence

    def validate(self, decision: MemoryDecision, candidate: Candidate, evidence: list[Memory]) -> MemoryDecision:
        evidence_ids = {m.memory_id for m in evidence}

        if decision.action in _TARGET_REQUIRED_ACTIONS:
            if decision.target_memory_id is None or decision.target_memory_id not in evidence_ids:
                return replace(
                    decision,
                    action=ReconciliationAction.CREATE,
                    target_memory_id=None,
                    reasoning=f"{decision.reasoning} (downgraded: target not in retrieved evidence)".strip(),
                )

        if decision.action != ReconciliationAction.IGNORE and decision.confidence < self.min_confidence:
            return replace(
                decision,
                action=ReconciliationAction.IGNORE,
                target_memory_id=None,
                reasoning=f"{decision.reasoning} (downgraded: confidence below {self.min_confidence})".strip(),
            )

        return decision
