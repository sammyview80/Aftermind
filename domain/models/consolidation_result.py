from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4


@dataclass(frozen=True)
class ConsolidationResult:
    """The outcome of validating (and, if accepted, applying) a
    ConsolidationCandidate — whether it became durable knowledge, where,
    and which memories it's derived from. Provenance
    (`source_memory_ids`) is kept regardless of outcome; consolidation
    never deletes or mutates the source memories."""

    result_id: str = field(default_factory=lambda: str(uuid4()))
    candidate_id: str = ""
    accepted: bool = False
    document_id: Optional[str] = None
    document_slug: Optional[str] = None
    source_memory_ids: tuple[str, ...] = field(default_factory=tuple)
    reasoning: str = ""
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_memory_ids", tuple(self.source_memory_ids))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
