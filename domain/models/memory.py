from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.enums.memory_type import MemoryType
from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class Memory:
    """A persisted, reconciled unit of memory — the durable end state of
    the pipeline (Event -> Experience -> Candidate -> Memory).

    Reconciliation (core/reconciliation) is what produces and updates
    these; Memory itself is just the stored shape.
    """

    memory_id: str = field(default_factory=lambda: str(uuid4()))
    scope: Optional[MemoryScope] = None
    content: str = ""
    memory_type: MemoryType = MemoryType.SEMANTIC

    entities: tuple[str, ...] = field(default_factory=tuple)
    relationships: tuple[str, ...] = field(default_factory=tuple)

    confidence: float = 0.0
    version: int = 1
    superseded_by: Optional[str] = None
    source_candidate_ids: tuple[str, ...] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "entities", tuple(self.entities))
        object.__setattr__(self, "relationships", tuple(self.relationships))
        object.__setattr__(self, "source_candidate_ids", tuple(self.source_candidate_ids))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
