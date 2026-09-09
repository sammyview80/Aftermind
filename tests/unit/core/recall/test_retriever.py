from typing import Optional

from core.recall.planner import RecallPlan
from core.recall.retriever import Retriever
from domain.enums.memory_domain import MemoryDomain
from domain.enums.memory_type import MemoryType
from domain.models.memory import Memory
from domain.models.scope import MemoryScope


class FakeKnowledgeStore:
    def __init__(self, memories: list[Memory]) -> None:
        self._memories = memories

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        words = set(query.lower().split())
        return [
            m for m in self._memories if m.superseded_by is None and words & set(m.content.lower().split())
        ][:limit]

    def get(self, memory_id: str) -> Optional[Memory]:
        return next((m for m in self._memories if m.memory_id == memory_id), None)

    def save(self, memory: Memory) -> Memory:
        self._memories.append(memory)
        return memory

    def history(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        words = set(query.lower().split())
        return [
            m for m in self._memories if m.superseded_by is not None and words & set(m.content.lower().split())
        ][:limit]


class FakeGraphStore:
    def __init__(self, related: dict[str, list[str]], relationships: dict[str, list[tuple[str, str, str]]] = None) -> None:
        self._related = related
        self._relationships = relationships or {}

    def upsert_entity(self, name: str, scope=None) -> None:
        pass

    def upsert_relationship(self, source, relation, target, scope=None) -> None:
        pass

    def find_related(self, entity: str, scope=None, limit: int = 5) -> list[str]:
        return self._related.get(entity, [])[:limit]

    def find_relationships(self, entity: str, scope=None, limit: int = 5) -> list[tuple[str, str, str]]:
        return self._relationships.get(entity, [])[:limit]


class FakeEmbedder:
    """Deterministic stand-in: embeds a piece of text as a one-hot
    vector over a fixed vocabulary, so cosine similarity behaves
    predictably in tests without a real model dependency."""

    def __init__(self, vocab: tuple[str, ...]) -> None:
        self._vocab = vocab

    def embed(self, text: str) -> tuple[float, ...]:
        words = set(text.lower().split())
        return tuple(1.0 if word in words else 0.0 for word in self._vocab)


class FakeVectorStore:
    def __init__(self) -> None:
        self._by_scope: dict[str, dict[str, tuple[float, ...]]] = {}

    def _key(self, scope) -> str:
        return scope.key() if scope is not None else "*"

    def upsert(self, memory_id, scope, embedding, model) -> None:
        self._by_scope.setdefault(self._key(scope), {})[memory_id] = embedding

    def search_similar(self, scope, query_embedding, limit=5):
        import math

        def cosine(a, b):
            dot = sum(x * y for x, y in zip(a, b))
            na = math.sqrt(sum(x * x for x in a))
            nb = math.sqrt(sum(y * y for y in b))
            return 0.0 if na == 0 or nb == 0 else dot / (na * nb)

        scored = [
            (memory_id, cosine(query_embedding, embedding))
            for memory_id, embedding in self._by_scope.get(self._key(scope), {}).items()
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]

    def delete(self, memory_id) -> None:
        for bucket in self._by_scope.values():
            bucket.pop(memory_id, None)


def _plan(**overrides) -> RecallPlan:
    base = dict(scope=None, fetch_checkpoint=True, search_terms=(), memory_types=(), entity_seeds=(), limit=5)
    base.update(overrides)
    return RecallPlan(**base)


def test_retrieve_collects_memories_across_search_terms_without_duplicates():
    shared = Memory(content="login flow uses OAuth")
    store = FakeKnowledgeStore([shared, Memory(content="unrelated fact about billing")])
    retriever = Retriever(store, FakeGraphStore({}))

    plan = _plan(search_terms=("login flow", "OAuth"))
    evidence = retriever.retrieve(plan)

    assert evidence.memories == (shared,)


def test_retrieve_filters_by_memory_type():
    episodic = Memory(content="ran tests", memory_type=MemoryType.EPISODIC)
    semantic = Memory(content="ran tests", memory_type=MemoryType.SEMANTIC)
    store = FakeKnowledgeStore([episodic, semantic])
    retriever = Retriever(store, FakeGraphStore({}))

    plan = _plan(search_terms=("ran tests",), memory_types=(MemoryType.SEMANTIC,))
    evidence = retriever.retrieve(plan)

    assert evidence.memories == (semantic,)


def test_retrieve_collects_related_entities_across_seeds_without_duplicates():
    graph = FakeGraphStore({"login": ["auth_module", "session"], "oauth": ["session"]})
    retriever = Retriever(FakeKnowledgeStore([]), graph)

    plan = _plan(entity_seeds=("login", "oauth"))
    evidence = retriever.retrieve(plan)

    assert evidence.related_entities == ("auth_module", "session")


def test_retrieve_with_no_plan_terms_returns_nothing():
    retriever = Retriever(FakeKnowledgeStore([Memory(content="anything")]), FakeGraphStore({}))
    evidence = retriever.retrieve(_plan())

    assert evidence.memories == ()
    assert evidence.related_entities == ()


def test_retrieve_collects_relationships_across_seeds():
    graph = FakeGraphStore(
        related={},
        relationships={"rabbitmq": [("RabbitMQ", "part_of", "payments architecture")]},
    )
    retriever = Retriever(FakeKnowledgeStore([]), graph)

    plan = _plan(entity_seeds=("rabbitmq",))
    evidence = retriever.retrieve(plan)

    assert evidence.relationships == (("RabbitMQ", "part_of", "payments architecture"),)


def test_retrieve_filters_by_memory_domain():
    project_fact = Memory(content="ran tests", memory_domain=MemoryDomain.PROJECT)
    org_fact = Memory(content="ran tests", memory_domain=MemoryDomain.ORGANIZATION)
    store = FakeKnowledgeStore([project_fact, org_fact])
    retriever = Retriever(store, FakeGraphStore({}))

    plan = _plan(search_terms=("ran tests",), domains=(MemoryDomain.ORGANIZATION,))
    evidence = retriever.retrieve(plan)

    assert evidence.memories == (org_fact,)


def test_retrieve_with_no_domains_set_returns_everything():
    project_fact = Memory(content="ran tests", memory_domain=MemoryDomain.PROJECT)
    org_fact = Memory(content="ran tests", memory_domain=MemoryDomain.ORGANIZATION)
    store = FakeKnowledgeStore([project_fact, org_fact])
    retriever = Retriever(store, FakeGraphStore({}))

    plan = _plan(search_terms=("ran tests",))
    evidence = retriever.retrieve(plan)

    assert {m.memory_id for m in evidence.memories} == {project_fact.memory_id, org_fact.memory_id}


def test_retrieve_skips_graph_when_not_included():
    graph = FakeGraphStore({"login": ["auth_module"]})
    retriever = Retriever(FakeKnowledgeStore([]), graph)

    plan = _plan(entity_seeds=("login",), include_graph=False)
    evidence = retriever.retrieve(plan)

    assert evidence.related_entities == ()


def test_retrieve_merges_semantic_hits_with_no_keyword_overlap():
    # "continue what we were doing" shares zero words with "SQLite" —
    # exactly the vocabulary-mismatch case keyword search alone misses.
    memory = Memory(content="Aftermind uses SQLite for canonical storage")
    store = FakeKnowledgeStore([memory])
    vocab = ("sqlite", "continue", "billing")
    embedder = FakeEmbedder(vocab)
    vector_store = FakeVectorStore()
    vector_store.upsert(memory.memory_id, None, embedder.embed(memory.content), model="fake")
    retriever = Retriever(store, FakeGraphStore({}), embedder=embedder, vector_store=vector_store)

    plan = _plan(search_terms=("what database do we use sqlite",))
    evidence = retriever.retrieve(plan)

    assert evidence.memories == (memory,)


def test_retrieve_ignores_semantic_hits_below_similarity_threshold():
    memory = Memory(content="unrelated content entirely")
    store = FakeKnowledgeStore([memory])
    embedder = FakeEmbedder(("sqlite", "billing"))
    vector_store = FakeVectorStore()
    vector_store.upsert(memory.memory_id, None, (0.0, 0.0), model="fake")
    retriever = Retriever(store, FakeGraphStore({}), embedder=embedder, vector_store=vector_store)

    plan = _plan(search_terms=("sqlite",))
    evidence = retriever.retrieve(plan)

    assert evidence.memories == ()


def test_retrieve_filters_semantic_hits_by_domain():
    project_fact = Memory(content="uses sqlite", memory_domain=MemoryDomain.PROJECT)
    org_fact = Memory(content="uses sqlite", memory_domain=MemoryDomain.ORGANIZATION)
    store = FakeKnowledgeStore([project_fact, org_fact])
    embedder = FakeEmbedder(("sqlite",))
    vector_store = FakeVectorStore()
    vector_store.upsert(project_fact.memory_id, None, (1.0,), model="fake")
    vector_store.upsert(org_fact.memory_id, None, (1.0,), model="fake")
    retriever = Retriever(store, FakeGraphStore({}), embedder=embedder, vector_store=vector_store)

    plan = _plan(search_terms=("sqlite",), domains=(MemoryDomain.ORGANIZATION,))
    evidence = retriever.retrieve(plan)

    assert evidence.memories == (org_fact,)


def test_retrieve_without_embedder_skips_semantic_search():
    retriever = Retriever(FakeKnowledgeStore([Memory(content="anything")]), FakeGraphStore({}))
    evidence = retriever.retrieve(_plan(search_terms=("anything",)))
    # No crash, no embedder configured — plain FTS/keyword path only.
    assert isinstance(evidence.memories, tuple)


def test_retrieve_collects_historical_memories_excluding_live_ones():
    live = Memory(content="Billing now uses RabbitMQ")
    superseded = Memory(content="Billing used Redis before", superseded_by=live.memory_id)
    store = FakeKnowledgeStore([live, superseded])
    retriever = Retriever(store, FakeGraphStore({}))

    plan = _plan(search_terms=("billing",))
    evidence = retriever.retrieve(plan)

    assert evidence.memories == (live,)
    assert evidence.historical_memories == (superseded,)
