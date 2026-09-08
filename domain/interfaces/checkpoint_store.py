from typing import Optional, Protocol

from domain.models.checkpoint import Checkpoint
from domain.models.scope import MemoryScope


class CheckpointStore(Protocol):
    """Persistence for consolidation checkpoints."""

    def save(self, checkpoint: Checkpoint) -> Checkpoint: ...

    def latest(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]: ...
