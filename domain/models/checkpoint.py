from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class Checkpoint:
    """A saved, versioned point an agent's work can resume from later.

    Structured as goal/completed/current/blockers/next — the same shape
    a human hands off a task with — rather than one free-text blob, so
    recall can rebuild "where I left off" without re-reading raw history.
    `memory_ids` pins the memories that were live/relevant at the time,
    `last_experience_id` points at the most recent experience folded in.
    """

    checkpoint_id: str = field(default_factory=lambda: str(uuid4()))
    scope: Optional[MemoryScope] = None
    version: int = 1

    goal: str = ""
    completed: tuple[str, ...] = field(default_factory=tuple)
    current: str = ""
    blockers: tuple[str, ...] = field(default_factory=tuple)
    next_steps: tuple[str, ...] = field(default_factory=tuple)

    memory_ids: tuple[str, ...] = field(default_factory=tuple)
    last_experience_id: Optional[str] = None
    reason: str = ""  # what triggered this checkpoint, e.g. "task_completed"
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "completed", tuple(self.completed))
        object.__setattr__(self, "blockers", tuple(self.blockers))
        object.__setattr__(self, "next_steps", tuple(self.next_steps))
        object.__setattr__(self, "memory_ids", tuple(self.memory_ids))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
