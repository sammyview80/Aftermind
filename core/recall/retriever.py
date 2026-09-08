from dataclasses import dataclass, field

from core.recall.planner import RecallPlan
from domain.interfaces.graph_store import GraphStore
from domain.interfaces.knowledge_store import KnowledgeStore
from domain.models.memory import Memory


@dataclass(frozen=True)
class RetrievedEvidence:
    """Raw candidates pulled for a plan, before ranking/compression."""

    memories: tuple[Memory, ...] = field(default_factory=tuple)
    related_entities: tuple[str, ...] = field(default_factory=tuple)


class Retriever:
    """Fetches candidate memories and related entities for a RecallPlan,
    from whatever storage backends are wired in (in-memory fakes in
    tests, Postgres/OpenKnowledge + Neo4j/Graphiti in production)."""

    def __init__(self, knowledge_store: KnowledgeStore, graph_store: GraphStore) -> None:
        self._knowledge_store = knowledge_store
        self._graph_store = graph_store

    def retrieve(self, plan: RecallPlan) -> RetrievedEvidence:
        by_id: dict[str, Memory] = {}
        for term in plan.search_terms:
            for memory in self._knowledge_store.search(term, scope=plan.scope, limit=plan.limit):
                if not plan.memory_types or memory.memory_type in plan.memory_types:
                    by_id.setdefault(memory.memory_id, memory)

        entities: dict[str, None] = {}
        for seed in plan.entity_seeds:
            for related in self._graph_store.find_related(seed, scope=plan.scope, limit=plan.limit):
                entities.setdefault(related, None)

        return RetrievedEvidence(memories=tuple(by_id.values()), related_entities=tuple(entities))
