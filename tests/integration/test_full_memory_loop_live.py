"""The first TRUE end-to-end memory test: real LLM calls (via
OpenRouterProvider / any OpenAI-compatible endpoint configured in
.env), driving the actual formation + reconciliation pipeline.

Storage is still an in-memory KnowledgeStore fake matching the
Postgres-facing Protocol exactly — this proves the LLM wiring and
prompts, not a Postgres deployment. Only the model calls are real.

Skipped automatically unless LLM_API_KEY (and LLM_MODEL) are set — see
.env.example. Not part of the default fast test loop: it makes real
network calls and its exact wording is model-dependent, so assertions
check the pipeline's *decisions* (create/supersede/ignore, final
recall content) rather than exact text.
"""
from typing import Optional

import pytest

from core.formation.candidate_extractor import LLMCandidateExtractor
from core.formation.evaluator import LLMMemoryEvaluator
from core.recall.context_builder import ContextBuilder
from core.recall.planner import RecallPlanner
from core.recall.ranker import Ranker
from core.recall.retriever import Retriever
from core.reconciliation.evidence_retriever import EvidenceRetriever
from core.reconciliation.reconciler import Reconciler
from core.reconciliation.validator import Validator
from domain.enums.event_type import EventType
from domain.enums.reconciliation_action import ReconciliationAction
from domain.models.checkpoint import Checkpoint
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.memory import Memory
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope
from providers.llm.base import load_prompt
from providers.llm.config import get_llm_config
from providers.llm.openrouter import OpenRouterProvider

_config = get_llm_config()

pytestmark = pytest.mark.skipif(
    not (_config.api_key and _config.model),
    reason="LLM_API_KEY/LLM_MODEL not set — see .env.example to run the live end-to-end test",
)


class FakeKnowledgeStore:
    """Stands in for the Postgres-backed KnowledgeStore — same Protocol,
    in-memory implementation. Only the LLM calls in this test are real."""

    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        query_words = _words(query)

        def overlap(memory: Memory) -> float:
            memory_words = _words(memory.content)
            if not query_words or not memory_words:
                return 0.0
            return len(query_words & memory_words) / len(query_words | memory_words)

        live = [m for m in self._memories.values() if m.superseded_by is None]
        matched = sorted((m for m in live if overlap(m) > 0), key=overlap, reverse=True)
        if matched:
            return matched[:limit]

        # No literal keyword overlap with a paraphrased candidate — a real
        # embedding-based search (Postgres+pgvector, Graphiti) would still
        # surface semantically related memories here. This word-overlap
        # fake can't do that, so approximate it with recency instead of
        # returning nothing, which would starve the reconciler of
        # evidence it should have had.
        return sorted(live, key=lambda m: m.updated_at, reverse=True)[:limit]

    def get(self, memory_id: str) -> Optional[Memory]:
        return self._memories.get(memory_id)

    def save(self, memory: Memory) -> Memory:
        self._memories[memory.memory_id] = memory
        return memory


class FakeGraphStore:
    def upsert_entity(self, name, scope=None) -> None:
        pass

    def upsert_relationship(self, source, relation, target, scope=None) -> None:
        pass

    def find_related(self, entity: str, scope=None, limit: int = 5) -> list[str]:
        return []


class FakeCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: list[Checkpoint] = []

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        self._checkpoints.append(checkpoint)
        return checkpoint

    def latest(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        matching = [c for c in self._checkpoints if c.scope == scope]
        return matching[-1] if matching else None


def _words(text: str) -> set[str]:
    return {w.strip(".,!?").lower() for w in text.split() if w.strip(".,!?")}


# Real models score bare, context-free statements ("We use Redis.")
# more conservatively than the rule-based heuristic evaluator does —
# there's no surrounding conversation signaling it's a confirmed
# decision. Lower the bar accordingly for this live test; the default
# threshold (core/formation/evaluator.py) is unchanged for everything else.
_LIVE_WORTH_REMEMBERING_THRESHOLD = 0.3


class MemoryPipeline:
    def __init__(self, knowledge_store: FakeKnowledgeStore, llm) -> None:
        self.knowledge_store = knowledge_store
        self.extractor = LLMCandidateExtractor(llm, system_prompt=load_prompt("candidate_extractor"))
        self.evaluator = LLMMemoryEvaluator(
            llm, system_prompt=load_prompt("evaluator"), threshold=_LIVE_WORTH_REMEMBERING_THRESHOLD
        )
        self.evidence_retriever = EvidenceRetriever(knowledge_store)
        self.reconciler = Reconciler(llm, system_prompt=load_prompt("reconciler"))
        self.validator = Validator()

    def learn(self, experience: Experience):
        candidates = self.extractor.extract(experience)
        if not candidates:
            return None, None

        candidate = self.evaluator.evaluate(candidates[0])
        if not self.evaluator.is_worth_remembering(candidate):
            return None, None

        evidence = self.evidence_retriever.retrieve(candidate)
        decision = self.reconciler.reconcile(candidate, evidence)
        decision = self.validator.validate(decision, candidate, evidence)

        return decision, self.reconciler.apply(decision, candidate, self.knowledge_store)


def _experience(text: str, scope: MemoryScope) -> Experience:
    return Experience(scope=scope, events=[Event(event_type=EventType.AGENT_MESSAGE)], output=text)


@pytest.fixture
def llm():
    return OpenRouterProvider()


def test_live_persistent_learning_loop_across_sessions(llm):
    scope = MemoryScope.of(tenant_id="live-test", project_id="aftermind")
    knowledge_store = FakeKnowledgeStore()
    pipeline = MemoryPipeline(knowledge_store, llm)

    # 1. "We use Redis." -> CREATE
    decision, redis_memory = pipeline.learn(_experience("We use Redis.", scope))
    assert redis_memory is not None, f"expected a memory to be created, got decision={decision}"
    assert decision.action == ReconciliationAction.CREATE

    # 2. "We switched to RabbitMQ." -> SUPERSEDE Redis
    decision, rabbitmq_memory = pipeline.learn(_experience("We switched to RabbitMQ.", scope))
    assert rabbitmq_memory is not None, f"expected a memory, got decision={decision}"
    assert decision.action == ReconciliationAction.SUPERSEDE
    assert "rabbitmq" in rabbitmq_memory.content.lower()

    stale_redis = knowledge_store.get(redis_memory.memory_id)
    assert stale_redis.superseded_by == rabbitmq_memory.memory_id

    # 3. "Okay thanks." -> IGNORE (no candidate, or no memory produced)
    _, ignored_memory = pipeline.learn(_experience("Okay thanks.", scope))
    assert ignored_memory is None

    # 4. New session: recall "What messaging system are we using?" -> RabbitMQ
    graph_store = FakeGraphStore()
    checkpoint_store = FakeCheckpointStore()
    planner = RecallPlanner()
    retriever = Retriever(knowledge_store, graph_store)
    ranker = Ranker()
    context_builder = ContextBuilder()

    query = RecallQuery(scope=scope, text="What messaging system are we using?")
    checkpoint = checkpoint_store.latest(scope)
    plan = planner.plan(query, checkpoint)
    evidence = retriever.retrieve(plan)
    ranked = ranker.rank(plan.search_terms, list(evidence.memories))
    context = context_builder.build(checkpoint, ranked, evidence.related_entities)

    assert ranked, "expected the RabbitMQ memory to be retrieved"
    assert "rabbitmq" in ranked[0].content.lower()
    assert redis_memory.memory_id not in [m.memory_id for m in ranked]
    assert "rabbitmq" in context.lower()
