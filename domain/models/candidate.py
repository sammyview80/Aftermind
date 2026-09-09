from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.enums.memory_domain import MemoryDomain
from domain.enums.memory_type import MemoryType
from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class Candidate:
    """A possible memory extracted from an experience, pending evaluation
    and reconciliation.

    This is the first point where Aftermind says "this might be worth
    remembering" — it does not yet decide that it *is*. Scoring
    (confidence, future_usefulness, durability, novelty, impact,
    specificity) is filled in by the memory evaluator; a Candidate only
    carries the content and the evaluator's verdict, not the evaluation
    logic itself. Only a downstream accept step turns a Candidate into a
    StoredMemory (domain/models/memory.py).
    """

    candidate_id: str = field(default_factory=lambda: str(uuid4()))
    experience_id: Optional[str] = None
    scope: Optional[MemoryScope] = None
    content: str = ""
    memory_type: MemoryType = MemoryType.SEMANTIC
    memory_domain: MemoryDomain = MemoryDomain.PROJECT

    entities: tuple[str, ...] = field(default_factory=tuple)
    relationships: tuple[str, ...] = field(default_factory=tuple)

    confidence: float = 0.0
    future_usefulness: float = 0.0
    durability: float = 0.0
    novelty: float = 0.0
    impact: float = 0.0
    specificity: float = 0.0

    user_confirmed: Optional[bool] = None
    source_event_ids: tuple[str, ...] = field(default_factory=tuple)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "entities", tuple(self.entities))
        object.__setattr__(self, "relationships", tuple(self.relationships))
        object.__setattr__(self, "source_event_ids", tuple(self.source_event_ids))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
