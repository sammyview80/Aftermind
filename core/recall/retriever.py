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
    relationships: tuple[tuple[str, str, str], ...] = field(default_factory=tuple)
    historical_memories: tuple[Memory, ...] = field(default_factory=tuple)


class Retriever:
    """Fetches candidate memories, related entities/relationships, and
    superseded (historical) memories for a RecallPlan, from whatever
    storage backends are wired in (in-memory fakes in tests, SQLite +
    Neo4j/Graphiti in production) — the "retrieve in parallel" half of
    hybrid recall; fan-out here is sequential but each source is
    independent and cheap, matching the plan's terms/seeds only."""

    def __init__(self, knowledge_store: KnowledgeStore, graph_store: GraphStore) -> None:
        self._knowledge_store = knowledge_store
        self._graph_store = graph_store

    def retrieve(self, plan: RecallPlan) -> RetrievedEvidence:
        # Durable memories/entities are stored under stabilized scope
        # (see reconciler.apply, graphiti store) — search with the same
        # stabilization so a new session's scope (different session_id/
        # run_id) still finds them.
        scope = plan.scope.stable() if plan.scope else None

        by_id: dict[str, Memory] = {}
        for term in plan.search_terms:
            for memory in self._knowledge_store.search(term, scope=scope, limit=plan.limit):
                if not plan.memory_types or memory.memory_type in plan.memory_types:
                    by_id.setdefault(memory.memory_id, memory)

        entities: dict[str, None] = {}
        relationships: dict[tuple[str, str, str], None] = {}
        for seed in plan.entity_seeds:
            for related in self._graph_store.find_related(seed, scope=scope, limit=plan.limit):
                entities.setdefault(related, None)
            find_relationships = getattr(self._graph_store, "find_relationships", None)
            if find_relationships is not None:
                for triple in find_relationships(seed, scope=scope, limit=plan.limit):
                    relationships.setdefault(tuple(triple), None)

        historical: dict[str, Memory] = {}
        history = getattr(self._knowledge_store, "history", None)
        if history is not None:
            for term in plan.search_terms:
                for memory in history(term, scope=scope, limit=plan.limit):
                    if memory.memory_id not in by_id:
                        historical.setdefault(memory.memory_id, memory)

        return RetrievedEvidence(
            memories=tuple(by_id.values()),
            related_entities=tuple(entities),
            relationships=tuple(relationships),
            historical_memories=tuple(historical.values()),
        )
