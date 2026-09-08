from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.enums.memory_type import MemoryType
from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class RecallQuery:
    """A request to reconstruct context for an agent — "continue this",
    "what do we know about X" — before any planning/retrieval happens."""

    query_id: str = field(default_factory=lambda: str(uuid4()))
    scope: Optional[MemoryScope] = None
    text: str = ""
    memory_types: tuple[MemoryType, ...] = field(default_factory=tuple)
    limit: int = 10
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_types", tuple(self.memory_types))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
