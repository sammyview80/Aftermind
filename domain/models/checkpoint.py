from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class Checkpoint:
    """A saved point an agent's work can resume from later.

    Answers "where did I leave off?" — `summary` is the human/agent-
    readable state of the work, `memory_ids` pins the memories that were
    live/relevant at the time, `last_experience_id` points at the most
    recent experience folded in. Recall planning (core/recall) starts
    from the latest checkpoint for a scope, not from raw history.
    """

    checkpoint_id: str = field(default_factory=lambda: str(uuid4()))
    scope: Optional[MemoryScope] = None
    summary: str = ""
    memory_ids: tuple[str, ...] = field(default_factory=tuple)
    last_experience_id: Optional[str] = None
    reason: str = ""  # what triggered this checkpoint, e.g. "task_completed"
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "memory_ids", tuple(self.memory_ids))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
