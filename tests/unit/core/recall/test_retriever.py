from typing import Optional

from core.recall.planner import RecallPlan
from core.recall.retriever import Retriever
from domain.enums.memory_type import MemoryType
from domain.models.memory import Memory
from domain.models.scope import MemoryScope


class FakeKnowledgeStore:
    def __init__(self, memories: list[Memory]) -> None:
        self._memories = memories

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        words = set(query.lower().split())
        return [m for m in self._memories if words & set(m.content.lower().split())][:limit]

    def get(self, memory_id: str) -> Optional[Memory]:
        return next((m for m in self._memories if m.memory_id == memory_id), None)

    def save(self, memory: Memory) -> Memory:
        self._memories.append(memory)
        return memory


class FakeGraphStore:
    def __init__(self, related: dict[str, list[str]]) -> None:
        self._related = related

    def upsert_entity(self, name: str, scope=None) -> None:
        pass

    def upsert_relationship(self, source, relation, target, scope=None) -> None:
        pass

    def find_related(self, entity: str, scope=None, limit: int = 5) -> list[str]:
        return self._related.get(entity, [])[:limit]


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
