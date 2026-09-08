from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.models.checkpoint import Checkpoint
from domain.models.memory import Memory


@dataclass(frozen=True)
class RecallResult:
    """The output of the recall pipeline: the checkpoint and memories
    selected as relevant, and the compact context built from them —
    ready to hand to the agent."""

    result_id: str = field(default_factory=lambda: str(uuid4()))
    query_id: str = ""
    checkpoint: Optional[Checkpoint] = None
    memories: tuple[Memory, ...] = field(default_factory=tuple)
    related_entities: tuple[str, ...] = field(default_factory=tuple)
    context: str = ""
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "memories", tuple(self.memories))
        object.__setattr__(self, "related_entities", tuple(self.related_entities))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
