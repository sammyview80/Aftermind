from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.enums.reconciliation_action import ReconciliationAction


@dataclass(frozen=True)
class MemoryDecision:
    """The recorded verdict on a candidate: whether it was worth
    remembering, and — if so — how it was reconciled against existing
    memory.

    Produced by core/reconciliation/reconciler.py after searching existing
    memory for evidence (core/reconciliation/evidence_retriever.py) and
    checked by core/reconciliation/validator.py before a Memory is
    created, updated, merged, or superseded. This model only records the
    decision — it carries no evaluation or reconciliation logic itself.
    """

    decision_id: str = field(default_factory=lambda: str(uuid4()))
    candidate_id: str = ""
    action: ReconciliationAction = ReconciliationAction.IGNORE
    target_memory_id: Optional[str] = None
    evidence_memory_ids: tuple[str, ...] = field(default_factory=tuple)
    confidence: float = 0.0
    reasoning: str = ""
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence_memory_ids", tuple(self.evidence_memory_ids))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
