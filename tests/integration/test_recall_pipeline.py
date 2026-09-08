"""End-to-end test of the recall pipeline:

    RecallQuery -> Planner -> Retriever -> Ranker -> ContextBuilder -> RecallResult

Fakes stand in for the checkpoint/knowledge/graph stores — no Postgres,
no Neo4j, no OpenKnowledge yet.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.recall.context_builder import ContextBuilder
from core.recall.planner import RecallPlanner
from core.recall.ranker import Ranker
from core.recall.retriever import Retriever
from domain.enums.memory_type import MemoryType
from domain.models.checkpoint import Checkpoint
from domain.models.memory import Memory
from domain.models.recall_query import RecallQuery
from domain.models.recall_result import RecallResult
from domain.models.scope import MemoryScope


class FakeCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: list[Checkpoint] = []

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        self._checkpoints.append(checkpoint)
        return checkpoint

    def latest(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        matching = [c for c in self._checkpoints if c.scope == scope]
        return matching[-1] if matching else None


class FakeKnowledgeStore:
    def __init__(self, memories: list[Memory]) -> None:
        self._memories = {m.memory_id: m for m in memories}

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        words = set(query.lower().split())
        matches = [m for m in self._memories.values() if words & set(m.content.lower().split())]
        return matches[:limit]


    def history(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        return []
    def get(self, memory_id: str) -> Optional[Memory]:
        return self._memories.get(memory_id)

    def save(self, memory: Memory) -> Memory:
        self._memories[memory.memory_id] = memory
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

    def find_relationships(self, entity: str, scope=None, limit: int = 5) -> list[tuple[str, str, str]]:
        return [(entity, "related_to", t) for t in self._related.get(entity, [])[:limit]]


class RecallService:
    """Wires the recall stages together, mirroring what an orchestrator
    would do in production."""

    def __init__(self, checkpoint_store, knowledge_store, graph_store) -> None:
        self.checkpoint_store = checkpoint_store
        self.planner = RecallPlanner()
        self.retriever = Retriever(knowledge_store, graph_store)
        self.ranker = Ranker()
        self.context_builder = ContextBuilder()

    def recall(self, query: RecallQuery) -> RecallResult:
        checkpoint = self.checkpoint_store.latest(query.scope)
        plan = self.planner.plan(query, checkpoint)
        evidence = self.retriever.retrieve(plan)
        ranked = self.ranker.rank(plan.search_terms, list(evidence.memories), limit=query.limit)
        context = self.context_builder.build(checkpoint, ranked, evidence.related_entities)

        return RecallResult(
            query_id=query.query_id,
            checkpoint=checkpoint,
            memories=tuple(ranked),
            related_entities=evidence.related_entities,
            context=context,
        )


def test_continue_aftermind_prioritizes_checkpoint_decisions_and_entities():
    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    checkpoint_store = FakeCheckpointStore()
    checkpoint_store.save(
        Checkpoint(
            scope=scope,
            goal="Build the memory formation pipeline",
            completed=("candidate extractor", "evaluator"),
            current="wiring reconciliation",
            blockers=(),
            next_steps=("build recall planner",),
        )
    )

    project_decision = Memory(
        scope=scope,
        content="Project decision: use word-overlap heuristics for the fake LLM reconciler",
        memory_type=MemoryType.SEMANTIC,
        confidence=0.9,
        updated_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    recent_task = Memory(
        scope=scope,
        content="Task memory: wired reconciliation validator and apply()",
        memory_type=MemoryType.EPISODIC,
        confidence=0.8,
        updated_at=datetime.now(timezone.utc),
    )
    unrelated = Memory(
        scope=scope,
        content="Unrelated fact about a different project entirely",
        memory_type=MemoryType.SEMANTIC,
        confidence=0.9,
        updated_at=datetime.now(timezone.utc),
    )

    knowledge_store = FakeKnowledgeStore([project_decision, recent_task, unrelated])
    graph_store = FakeGraphStore({"reconciliation": ["reconciler", "validator"]})

    service = RecallService(checkpoint_store, knowledge_store, graph_store)
    result = service.recall(RecallQuery(scope=scope, text="Continue Aftermind"))

    assert result.checkpoint.goal == "Build the memory formation pipeline"
    assert unrelated not in result.memories
    assert project_decision in result.memories
    assert recent_task in result.memories
    assert "reconciler" in result.related_entities
    assert "## Where you left off" in result.context
    assert "## Current facts" in result.context
    assert "## Related entities" in result.context


def test_recall_with_no_checkpoint_falls_back_to_query_text_only():
    scope = MemoryScope.of(tenant_id="t1")
    checkpoint_store = FakeCheckpointStore()
    memory = Memory(scope=scope, content="User prefers dark mode", confidence=0.9)
    knowledge_store = FakeKnowledgeStore([memory])
    graph_store = FakeGraphStore({})

    service = RecallService(checkpoint_store, knowledge_store, graph_store)
    result = service.recall(RecallQuery(scope=scope, text="dark mode"))

    assert result.checkpoint is None
    assert result.memories == (memory,)
    assert "## Where you left off" not in result.context
