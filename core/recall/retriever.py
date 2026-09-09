from dataclasses import dataclass, field
from typing import Optional

from core.observability import trace
from core.recall.planner import RecallPlan
from domain.interfaces.embedder import Embedder
from domain.interfaces.graph_store import GraphStore
from domain.interfaces.knowledge_store import KnowledgeStore
from domain.interfaces.vector_store import VectorStore
from domain.models.memory import Memory


# Below this cosine similarity, a semantic hit is noise, not signal —
# generic sentence embeddings rarely score near 1.0 even for genuinely
# related-but-differently-worded content, but unrelated content reliably
# scores well below this.
DEFAULT_MIN_SEMANTIC_SIMILARITY = 0.35


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
    independent and cheap, matching the plan's terms/seeds only.

    The knowledge store is canonical and its failure is a real failure.
    The graph store is a secondary source: if it is unreachable, recall
    degrades to memories-only (trace field graph_search=failed) rather
    than returning nothing.
    """

    def __init__(
        self,
        knowledge_store: KnowledgeStore,
        graph_store: GraphStore,
        embedder: Optional[Embedder] = None,
        vector_store: Optional[VectorStore] = None,
    ) -> None:
        self._knowledge_store = knowledge_store
        self._graph_store = graph_store
        self._embedder = embedder
        self._vector_store = vector_store

    def retrieve(self, plan: RecallPlan) -> RetrievedEvidence:
        # Durable memories/entities are stored under stabilized scope
        # (see reconciler.apply, graphiti store) — search with the same
        # stabilization so a new session's scope (different session_id/
        # run_id) still finds them.
        scope = plan.scope.stable() if plan.scope else None

        def in_domain(memory: Memory) -> bool:
            return not plan.domains or memory.memory_domain in plan.domains

        by_id: dict[str, Memory] = {}
        with trace.span("knowledge.search"):
            for term in plan.search_terms:
                for memory in self._knowledge_store.search(term, scope=scope, limit=plan.limit):
                    if (not plan.memory_types or memory.memory_type in plan.memory_types) and in_domain(memory):
                        by_id.setdefault(memory.memory_id, memory)

        if self._embedder is not None and self._vector_store is not None:
            with trace.span("semantic.retrieve", reraise=False) as span:
                for term in plan.search_terms:
                    query_embedding = self._embedder.embed(term)
                    for memory_id, similarity in self._vector_store.search_similar(scope, query_embedding, plan.limit):
                        if similarity < DEFAULT_MIN_SEMANTIC_SIMILARITY or memory_id in by_id:
                            continue
                        memory = self._knowledge_store.get(memory_id)
                        if memory is None or memory.superseded_by:
                            continue
                        if (not plan.memory_types or memory.memory_type in plan.memory_types) and in_domain(memory):
                            by_id.setdefault(memory.memory_id, memory)
            if span is not None and span.status == trace.FAILED:
                trace.record(semantic_search=trace.FAILED)

        entities: dict[str, None] = {}
        relationships: dict[tuple[str, str, str], None] = {}
        if plan.include_graph:
            with trace.span("graph.retrieve", reraise=False) as span:
                for seed in plan.entity_seeds:
                    for related in self._graph_store.find_related(seed, scope=scope, limit=plan.limit):
                        entities.setdefault(related, None)
                    for triple in self._graph_store.find_relationships(seed, scope=scope, limit=plan.limit):
                        relationships.setdefault(tuple(triple), None)
            if span is not None and span.status == trace.FAILED:
                trace.record(graph_search=trace.FAILED)

        historical: dict[str, Memory] = {}
        with trace.span("knowledge.history"):
            for term in plan.search_terms:
                for memory in self._knowledge_store.history(term, scope=scope, limit=plan.limit):
                    if memory.memory_id not in by_id and in_domain(memory):
                        historical.setdefault(memory.memory_id, memory)

        return RetrievedEvidence(
            memories=tuple(by_id.values()),
            related_entities=tuple(entities),
            relationships=tuple(relationships),
            historical_memories=tuple(historical.values()),
        )
