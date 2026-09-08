from typing import Protocol

from domain.models.scope import MemoryScope


class GraphStore(Protocol):
    """Persistence for entities/relationships extracted alongside a memory.
    Backed by Neo4j/Graphiti in production, an in-memory graph in tests."""

    def upsert_entity(self, name: str, scope: MemoryScope | None = None) -> None: ...

    def upsert_relationship(
        self, source: str, relation: str, target: str, scope: MemoryScope | None = None
    ) -> None: ...

    def find_related(self, entity: str, scope: MemoryScope | None = None, limit: int = 5) -> list[str]:
        """Return names of entities connected to `entity`, for surfacing
        during recall (e.g. "related entities" alongside retrieved memories).
        Excludes relationships marked historical via mark_historical()."""
        ...

    def find_relationships(
        self, entity: str, scope: MemoryScope | None = None, limit: int = 5
    ) -> list[tuple[str, str, str]]:
        """Return (source, relation, target) triples with `entity` as the
        source, for recall to surface *why* two entities are related
        (e.g. "RabbitMQ -[part_of]-> payments architecture"), not just
        that they are. Excludes relationships marked historical."""
        ...

    def mark_historical(
        self, source: str, relation: str, target: str, scope: MemoryScope | None = None
    ) -> None:
        """Mark one (source, relation, target) edge as historical — the
        memory that produced it was superseded, so the fact is no longer
        current, but the relationship isn't deleted: it's how a
        "Billing -[USES]-> Redis" edge stays answerable for "what did
        Billing use before?" after "Billing -[USES]-> RabbitMQ" becomes
        current. A no-op if no matching edge exists."""
        ...

    def find_historical_relationships(
        self, entity: str, scope: MemoryScope | None = None, limit: int = 5
    ) -> list[tuple[str, str, str]]:
        """The historical counterpart to find_relationships() — edges
        with `entity` as source that were marked historical."""
        ...
