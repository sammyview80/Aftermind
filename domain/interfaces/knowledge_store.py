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

    def list_all(self, scope: Optional[MemoryScope] = None, limit: int = 1000) -> list[Memory]:
        """All live (non-superseded) memories in scope — unlike search(),
        not ranked against a query. Used by consolidation, which needs
        every candidate in scope to cluster, not just the top-k for one
        query."""
        ...

    def history(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        """Superseded memories in scope relevant to `query` — used by
        recall to surface historical context (e.g. "Redis was replaced")
        alongside current facts, which search()/list_all() deliberately
        exclude."""
        ...
