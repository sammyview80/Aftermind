"""End-to-end test of the full persistent learning loop, LLM-powered
stages included:

    Experience -> LLMCandidateExtractor -> LLMMemoryEvaluator
        -> EvidenceRetriever (search Postgres-like store) -> Reconciler (LLM)
        -> Validator -> apply -> StoredMemory
        ... new session ...
        -> RecallQuery -> Planner -> Retriever -> Ranker -> ContextBuilder

Every stage's LLM calls go through one ScriptedLLMProvider that routes on
the *actual* system prompts loaded from providers/llm/prompts/*.md, so
this proves the prompts + provider wiring, not just the deterministic
core logic. The only thing faked is the model call itself — no network,
no API key, no real Postgres/Neo4j (a KnowledgeStore fake stands in for
Postgres, matching its Protocol exactly).
"""
import json
import re
from typing import Optional

import pytest

from core.checkpoints.manager import CheckpointManager
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
from domain.models.checkpoint import Checkpoint
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.memory import Memory
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope
from providers.llm.base import load_prompt


class FakeKnowledgeStore:
    """Stands in for the Postgres-backed KnowledgeStore — same Protocol,
    in-memory implementation."""

    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        query_words = _words(query)

        def overlap(memory: Memory) -> float:
            memory_words = _words(memory.content)
            if not query_words or not memory_words:
                return 0.0
            return len(query_words & memory_words) / len(query_words | memory_words)

        ranked = sorted((m for m in self._memories.values() if m.superseded_by is None), key=overlap, reverse=True)
        return [m for m in ranked if overlap(m) > 0][:limit]

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


_TRIVIAL_PHRASES = {"ok", "okay", "okay thanks", "thanks", "got it", "sure"}


class ScriptedLLMProvider:
    """One LLMProvider serving all three roles (extraction, evaluation,
    reconciliation), routing on the real system prompts each stage sends.
    Deterministic word-overlap heuristics stand in for the model itself."""

    def complete(self, prompt: str) -> str:
        if "Return a JSON array of candidates" in prompt:
            return self._extract(prompt)
        if '"worth_remembering"' in prompt:
            return self._evaluate()
        if "EXISTING MEMORIES:" in prompt:
            return self._reconcile(prompt)
        raise ValueError(f"unrecognized prompt shape: {prompt[:80]!r}")

    def _extract(self, prompt: str) -> str:
        output = re.search(r"output: (.*)", prompt).group(1).strip()
        if output.strip(".!").lower() in _TRIVIAL_PHRASES or not output:
            return "[]"

        # A real model normalizes transient phrasing ("switched to") into
        # a stable present-tense fact so it can be compared against
        # existing memory on the same footing.
        normalized = re.sub(r"\bswitched to\b", "use", output, flags=re.IGNORECASE)

        return json.dumps(
            [
                {
                    "content": normalized,
                    "memory_type": "semantic",
                    "entities": [],
                    "relationships": [],
                    "user_confirmed": True,
                    "confidence": 0.9,
                }
            ]
        )

    def _evaluate(self) -> str:
        return json.dumps(
            {
                "worth_remembering": True,
                "confidence": 0.9,
                "future_usefulness": 0.8,
                "durability": 0.8,
                "novelty": 0.7,
                "impact": 0.7,
                "specificity": 0.7,
                "reasoning": "Confirmed technical decision.",
            }
        )

    def _reconcile(self, prompt: str) -> str:
        candidate_content = prompt.split("CANDIDATE:\n", 1)[1].split("\n\nEXISTING MEMORIES:", 1)[0].strip()
        block = prompt.split("EXISTING MEMORIES:\n", 1)[1].split("\n\nRespond", 1)[0].strip()

        if block == "None found.":
            return json.dumps({"action": "create", "target_memory_id": None, "confidence": 0.9, "reasoning": "No related memory."})

        evidence = []
        for line in block.splitlines():
            memory_id, content = line.split("] ", 1)
            evidence.append((memory_id.split("[", 1)[1], content))

        candidate_words = _words(candidate_content)
        best_id, best_content, best_score = None, None, -1.0
        for memory_id, content in evidence:
            score = _jaccard(candidate_words, _words(content))
            if score > best_score:
                best_id, best_content, best_score = memory_id, content, score

        best_words = _words(best_content)
        removed = best_words - candidate_words
        added = candidate_words - best_words

        if not removed and not added:
            decision = {"action": "ignore", "target_memory_id": best_id, "confidence": 0.9, "reasoning": "Duplicate."}
        elif not removed and added:
            decision = {"action": "update", "target_memory_id": best_id, "confidence": 0.85, "reasoning": "More specific."}
        elif removed and added and len(best_words & candidate_words) / min(len(best_words), len(candidate_words)) >= 0.4:
            decision = {"action": "supersede", "target_memory_id": best_id, "confidence": 0.85, "reasoning": "Contradicts prior value."}
        else:
            decision = {"action": "create", "target_memory_id": None, "confidence": 0.7, "reasoning": "Unrelated."}

        return json.dumps(decision)


def _words(text: str) -> set[str]:
    return {w.strip(".,!?") .lower() for w in text.split() if w.strip(".,!?")}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class MemoryPipeline:
    def __init__(self, knowledge_store: FakeKnowledgeStore, llm) -> None:
        self.knowledge_store = knowledge_store
        self.extractor = LLMCandidateExtractor(llm, system_prompt=load_prompt("candidate_extractor"))
        self.evaluator = LLMMemoryEvaluator(llm, system_prompt=load_prompt("evaluator"))
        self.evidence_retriever = EvidenceRetriever(knowledge_store)
        self.reconciler = Reconciler(llm, system_prompt=load_prompt("reconciler"))
        self.validator = Validator()

    def learn(self, experience: Experience) -> Optional[Memory]:
        candidates = self.extractor.extract(experience)
        if not candidates:
            return None

        candidate = self.evaluator.evaluate(candidates[0])
        if not self.evaluator.is_worth_remembering(candidate):
            return None

        evidence = self.evidence_retriever.retrieve(candidate)
        decision = self.reconciler.reconcile(candidate, evidence)
        decision = self.validator.validate(decision, candidate, evidence)

        return self.reconciler.apply(decision, candidate, self.knowledge_store)


def _experience(text: str, scope: MemoryScope) -> Experience:
    return Experience(scope=scope, events=[Event(event_type=EventType.AGENT_MESSAGE)], output=text)


def test_full_persistent_learning_loop_across_sessions():
    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    llm = ScriptedLLMProvider()
    knowledge_store = FakeKnowledgeStore()
    pipeline = MemoryPipeline(knowledge_store, llm)

    # Session 1: "We use Redis." -> CREATE
    redis_memory = pipeline.learn(_experience("We use Redis.", scope))
    assert redis_memory is not None
    assert redis_memory.content == "We use Redis."
    assert redis_memory.version == 1

    # Session 1 continued: "We switched to RabbitMQ." -> SUPERSEDE Redis
    rabbitmq_memory = pipeline.learn(_experience("We switched to RabbitMQ.", scope))
    assert rabbitmq_memory is not None
    assert rabbitmq_memory.memory_id != redis_memory.memory_id
    assert "RabbitMQ" in rabbitmq_memory.content

    stale_redis = knowledge_store.get(redis_memory.memory_id)
    assert stale_redis.superseded_by == rabbitmq_memory.memory_id

    # Irrelevant content still produces no memory.
    assert pipeline.learn(_experience("okay thanks", scope)) is None

    # New session: recall "What messaging system are we using?"
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

    assert ranked
    assert ranked[0].content == rabbitmq_memory.content
    assert redis_memory.memory_id not in [m.memory_id for m in ranked]
    assert "RabbitMQ" in context
    assert "Redis" not in context
