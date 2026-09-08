from typing import Protocol

from domain.models.scope import MemoryScope


class GraphStore(Protocol):
    """Persistence for entities/relationships extracted alongside a memory.
    Backed by Neo4j/Graphiti in production, an in-memory graph in tests."""

    def upsert_entity(self, name: str, scope: MemoryScope | None = None) -> None: ...

    def upsert_relationship(
        self, source: str, relation: str, target: str, scope: MemoryScope | None = None
    ) -> None: ...
