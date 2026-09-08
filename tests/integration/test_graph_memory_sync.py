"""End-to-end test of the graph memory sync:

    StoredMemory -> extract entities+relationships (mapper.py) -> GraphStore

In-memory here, not a real Neo4j/Graphiti deployment (providers/graphiti/
client.py + store.py cover that against the real driver, exercised in
tests/unit/providers/graphiti/test_client.py and test_store.py with a
fake driver). This proves the Memory -> graph wiring end to end using a
fake matching the GraphStore Protocol exactly.

Expected graph, from:
    "Aftermind uses PostgreSQL."
    "Aftermind uses Graphiti."
    "Graphiti runs on Neo4j."

    Aftermind -> USES -> PostgreSQL
    Aftermind -> USES -> Graphiti
    Graphiti  -> RUNS_ON -> Neo4j
"""
from typing import Optional

from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from providers.graphiti.mapper import sync_to_graph


class InMemoryGraphStore:
    """Fake matching the GraphStore Protocol — an adjacency dict instead
    of a real Neo4j-backed graph."""

    def __init__(self) -> None:
        self.entities: set[tuple[str, str]] = set()
        self.edges: list[tuple[str, str, str, str]] = []  # (source, relation, target, scope_key)

    def upsert_entity(self, name: str, scope: Optional[MemoryScope] = None) -> None:
        self.entities.add((name, _scope_key(scope)))

    def upsert_relationship(
        self, source: str, relation: str, target: str, scope: Optional[MemoryScope] = None
    ) -> None:
        self.edges.append((source, relation, target, _scope_key(scope)))

    def find_related(self, entity: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[str]:
        scope_key = _scope_key(scope)
        return [t for s, _, t, sk in self.edges if s == entity and sk == scope_key][:limit]


def _scope_key(scope: Optional[MemoryScope]) -> str:
    return scope.key() if scope is not None else "*"


def test_three_facts_produce_expected_graph():
    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    graph_store = InMemoryGraphStore()

    memories = [
        Memory(scope=scope, content="Aftermind uses PostgreSQL."),
        Memory(scope=scope, content="Aftermind uses Graphiti."),
        Memory(scope=scope, content="Graphiti runs on Neo4j."),
    ]

    for memory in memories:
        sync_to_graph(memory, graph_store)

    assert ("Aftermind", "USES", "PostgreSQL") in [(s, r, t) for s, r, t, _ in graph_store.edges]
    assert ("Aftermind", "USES", "Graphiti") in [(s, r, t) for s, r, t, _ in graph_store.edges]
    assert ("Graphiti", "RUNS_ON", "Neo4j") in [(s, r, t) for s, r, t, _ in graph_store.edges]

    assert set(graph_store.find_related("Aftermind", scope=scope)) == {"PostgreSQL", "Graphiti"}
    assert graph_store.find_related("Graphiti", scope=scope) == ["Neo4j"]
    assert graph_store.find_related("Neo4j", scope=scope) == []


def test_scope_isolates_graph_traversal():
    scope_a = MemoryScope.of(tenant_id="t1")
    scope_b = MemoryScope.of(tenant_id="t2")
    graph_store = InMemoryGraphStore()

    sync_to_graph(Memory(scope=scope_a, content="Aftermind uses PostgreSQL."), graph_store)
    sync_to_graph(Memory(scope=scope_b, content="Aftermind uses MongoDB."), graph_store)

    assert graph_store.find_related("Aftermind", scope=scope_a) == ["PostgreSQL"]
    assert graph_store.find_related("Aftermind", scope=scope_b) == ["MongoDB"]
