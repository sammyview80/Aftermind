from typing import Optional

from domain.models.candidate import Candidate
from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from providers.graphiti.mapper import Triple, extract_triples, sync_to_graph, triples_from


def test_extract_triples_uses():
    assert extract_triples("Aftermind uses PostgreSQL.") == [Triple("Aftermind", "USES", "PostgreSQL")]


def test_extract_triples_runs_on():
    assert extract_triples("Graphiti runs on Neo4j.") == [Triple("Graphiti", "RUNS_ON", "Neo4j")]


def test_extract_triples_no_match_returns_empty():
    assert extract_triples("This sentence has no relation verb.") == []


def test_triples_from_prefers_structured_relationships_over_content():
    memory = Memory(content="irrelevant raw text", relationships=["Aftermind uses Graphiti"])
    assert triples_from(memory) == [Triple("Aftermind", "USES", "Graphiti")]


def test_triples_from_falls_back_to_content_when_no_relationships():
    candidate = Candidate(content="Aftermind uses PostgreSQL.")
    assert triples_from(candidate) == [Triple("Aftermind", "USES", "PostgreSQL")]


class FakeGraphStore:
    def __init__(self) -> None:
        self.entities: list[tuple[str, Optional[MemoryScope]]] = []
        self.relationships: list[tuple[str, str, str, Optional[MemoryScope]]] = []

    def upsert_entity(self, name, scope=None) -> None:
        self.entities.append((name, scope))

    def upsert_relationship(self, source, relation, target, scope=None) -> None:
        self.relationships.append((source, relation, target, scope))

    def find_related(self, entity, scope=None, limit=5) -> list[str]:
        return [t for s, r, t, sc in self.relationships if s == entity]


def test_sync_to_graph_writes_entities_and_relationship():
    scope = MemoryScope.of(tenant_id="t1")
    memory = Memory(scope=scope, content="Aftermind uses PostgreSQL.")
    store = FakeGraphStore()

    triples = sync_to_graph(memory, store)

    assert triples == [Triple("Aftermind", "USES", "PostgreSQL")]
    assert ("Aftermind", scope) in store.entities
    assert ("PostgreSQL", scope) in store.entities
    assert store.relationships == [("Aftermind", "USES", "PostgreSQL", scope)]


def test_sync_to_graph_with_no_triples_writes_nothing():
    store = FakeGraphStore()
    triples = sync_to_graph(Memory(content="no relation here"), store)

    assert triples == []
    assert store.entities == []
    assert store.relationships == []
