from typing import Optional, Protocol

from domain.models.memory import Memory
from domain.models.scope import MemoryScope


class KnowledgeStore(Protocol):
    """Persistence for StoredMemory. Backed by Postgres/OpenKnowledge in
    production, an in-memory dict in tests."""

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        """Return memories relevant to `query`, most relevant first."""
        ...

    def get(self, memory_id: str) -> Optional[Memory]: ...

    def save(self, memory: Memory) -> Memory:
        """Insert or overwrite a memory by id, returning the stored value."""
        ...
