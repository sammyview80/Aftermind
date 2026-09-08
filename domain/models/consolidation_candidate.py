from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class ConsolidationCandidate:
    """A proposed durable summary synthesized from a cluster of related
    StoredMemory — "these N memories together mean X". Pending
    validation before it's written into OpenKnowledge; the source
    memories are never deleted or replaced by this."""

    candidate_id: str = field(default_factory=lambda: str(uuid4()))
    scope: Optional[MemoryScope] = None
    topic: str = ""
    source_memory_ids: tuple[str, ...] = field(default_factory=tuple)
    proposed_content: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    trigger_reason: str = ""
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_memory_ids", tuple(self.source_memory_ids))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
