from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.enums.memory_status import MemoryStatus
from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class MemoryLifecycle:
    """Usage/health state for one Memory — kept separate from Memory
    itself so content and lifecycle can evolve independently (recording
    an access shouldn't touch the memory's content/version, and vice
    versa).

    `importance` and `decay_score` are independent dials: importance
    reflects how much reinforcement a memory has earned (goes up on
    access), decay_score reflects how stale it's gotten (goes up with
    disuse). `status` is the derived, actionable summary of both.
    """

    memory_id: str = ""
    scope: Optional[MemoryScope] = None
    status: MemoryStatus = MemoryStatus.ACTIVE
    importance: float = 0.5
    confidence: float = 0.0
    decay_score: float = 0.0
    access_count: int = 0
    last_accessed_at: Optional[datetime] = None
    valid_from: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    valid_until: Optional[datetime] = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def is_active_for_recall(self) -> bool:
        return self.status in (MemoryStatus.ACTIVE, MemoryStatus.DECAYED)
