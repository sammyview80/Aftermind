from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4

from domain.models.scope import MemoryScope


@dataclass
class Checkpoint:
    """A saved consolidation point an agent's memory state can resume from."""

    id: str = field(default_factory=lambda: str(uuid4()))
    scope: Optional[MemoryScope] = None
    memory_ids: list[str] = field(default_factory=list)
    reason: str = ""          # what triggered this checkpoint
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
