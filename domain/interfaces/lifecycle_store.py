from typing import Optional, Protocol

from domain.models.memory_lifecycle import MemoryLifecycle
from domain.models.scope import MemoryScope


class LifecycleStore(Protocol):
    """Persistence for MemoryLifecycle records — one per Memory."""

    def get(self, memory_id: str, scope: Optional[MemoryScope] = None) -> Optional[MemoryLifecycle]: ...

    def save(self, lifecycle: MemoryLifecycle) -> MemoryLifecycle: ...

    def list_all(self, scope: Optional[MemoryScope] = None) -> list[MemoryLifecycle]:
        """All lifecycle records in scope — used for decay sweeps."""
        ...
