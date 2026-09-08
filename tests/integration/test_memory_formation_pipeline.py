"""End-to-end test of the memory formation pipeline:

    Experience -> CandidateExtractor -> MemoryEvaluator -> EvidenceRetriever
        -> Reconciler (LLM) -> Validator -> apply -> StoredMemory

Everything here is in-memory/fake: no Postgres, no Neo4j, no OpenKnowledge,
no real LLM. Once this passes, the same pipeline is exercised again with
real adapters swapped in for the fakes.
"""
import json
from typing import Optional

import pytest

from core.formation.candidate_extractor import CandidateExtractor
from core.formation.evaluator import MemoryEvaluator
from core.reconciliation.evidence_retriever import EvidenceRetriever
from core.reconciliation.reconciler import Reconciler
from core.reconciliation.validator import Validator
from domain.enums.event_type import EventType
from domain.enums.reconciliation_action import ReconciliationAction
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.memory import Memory
from domain.models.scope import MemoryScope


class FakeKnowledgeStore:
    """In-memory KnowledgeStore. Search is plain word-overlap ranking —
    good enough to stand in for a real vector/keyword search in tests."""

    def __init__(self) -> None:
        self._memories: dict[str, Memory] = {}

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        query_words = _words(query)

        def overlap(memory: Memory) -> float:
            memory_words = _words(memory.content)
            if not query_words or not memory_words:
                return 0.0
            return len(query_words & memory_words) / len(query_words | memory_words)

        ranked = sorted(
            (m for m in self._memories.values() if m.superseded_by is None),
            key=overlap,
            reverse=True,
        )
        return [m for m in ranked if overlap(m) > 0][:limit]

    def get(self, memory_id: str) -> Optional[Memory]:
        return self._memories.get(memory_id)

    def save(self, memory: Memory) -> Memory:
        self._memories[memory.memory_id] = memory
        return memory


class FakeLLMProvider:
    """Deterministic stand-in for a real LLM reconciler. Reads the same
    prompt a real LLM would see and applies word-overlap heuristics
    instead of an actual model call, so the pipeline's wiring can be
    tested without network access or nondeterminism."""

    def complete(self, prompt: str) -> str:
        candidate_content = _extract_between(prompt, "CANDIDATE:\n", "\n\nEXISTING MEMORIES:")
        evidence = _extract_evidence(prompt)

        if not evidence:
            decision = {
                "action": "create",
                "target_memory_id": None,
                "confidence": 0.9,
                "reasoning": "No related memory found.",
            }
            return json.dumps(decision)

        candidate_words = _words(candidate_content)
        best_id, best_content, best_score = None, None, -1.0
        for memory_id, content in evidence:
            memory_words = _words(content)
            score = len(candidate_words & memory_words) / len(candidate_words | memory_words)
            if score > best_score:
                best_id, best_content, best_score = memory_id, content, score

        best_words = _words(best_content)
        removed = best_words - candidate_words
        added = candidate_words - best_words

        if not removed and not added:
            decision = {
                "action": "ignore",
                "target_memory_id": best_id,
                "confidence": 0.9,
                "reasoning": "Candidate restates an existing memory verbatim.",
            }
        elif not removed and added:
            decision = {
                "action": "update",
                "target_memory_id": best_id,
                "confidence": 0.85,
                "reasoning": "Candidate adds more specific detail to an existing memory.",
            }
        elif removed and added and len(removed & candidate_words | best_words) >= 0:
            # same skeleton (shared words) but at least one word swapped out
            # for another -> the fact itself changed, not just refined.
            shared_ratio = len(best_words & candidate_words) / min(len(best_words), len(candidate_words))
            if shared_ratio >= 0.4:
                decision = {
                    "action": "supersede",
                    "target_memory_id": best_id,
                    "confidence": 0.85,
                    "reasoning": "Candidate contradicts an existing memory's value for the same fact.",
                }
            else:
                decision = {
                    "action": "create",
                    "target_memory_id": None,
                    "confidence": 0.7,
                    "reasoning": "Candidate is unrelated to retrieved evidence.",
                }
        else:
            decision = {
                "action": "create",
                "target_memory_id": None,
                "confidence": 0.7,
                "reasoning": "Candidate is unrelated to retrieved evidence.",
            }

        return json.dumps(decision)


def _words(text: str) -> set[str]:
    return {w.strip(".,!?").lower() for w in text.split() if w.strip(".,!?")}


def _extract_between(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0].strip()


def _extract_evidence(prompt: str) -> list[tuple[str, str]]:
    block = prompt.split("EXISTING MEMORIES:\n", 1)[1].split("\n\nRespond", 1)[0].strip()
    if block == "None found.":
        return []
    results = []
    for line in block.splitlines():
        # "1. [mem_id] content"
        rest = line.split("] ", 1)
        memory_id = rest[0].split("[", 1)[1]
        content = rest[1]
        results.append((memory_id, content))
    return results


class Pipeline:
    """Wires the formation + reconciliation stages together, mirroring
    what an orchestrator would do in production."""

    def __init__(self, knowledge_store: FakeKnowledgeStore, llm_provider: FakeLLMProvider) -> None:
        self.knowledge_store = knowledge_store
        self.extractor = CandidateExtractor()
        self.evaluator = MemoryEvaluator()
        self.evidence_retriever = EvidenceRetriever(knowledge_store)
        self.reconciler = Reconciler(llm_provider)
        self.validator = Validator()

    def run(self, experience: Experience) -> Optional[Memory]:
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


def _experience(text: str, scope: Optional[MemoryScope] = None) -> Experience:
    return Experience(
        scope=scope or MemoryScope.of(tenant_id="t1"),
        events=[Event(event_type=EventType.AGENT_MESSAGE, payload={"text": text})],
        output=text,
    )


@pytest.fixture
def pipeline() -> Pipeline:
    return Pipeline(FakeKnowledgeStore(), FakeLLMProvider())


def test_new_fact_with_no_existing_memory_is_created(pipeline: Pipeline):
    memory = pipeline.run(_experience("The team's primary database is Postgres"))

    assert memory is not None
    assert memory.content == "The team's primary database is Postgres"
    assert memory.version == 1
    assert pipeline.knowledge_store.get(memory.memory_id) is memory


def test_duplicate_fact_is_ignored(pipeline: Pipeline):
    first = pipeline.run(_experience("The team's primary database is Postgres"))
    second = pipeline.run(_experience("The team's primary database is Postgres"))

    assert second is None
    assert pipeline.knowledge_store.get(first.memory_id) == first  # untouched


def test_more_specific_fact_updates_existing_memory(pipeline: Pipeline):
    original = pipeline.run(_experience("User is a data scientist"))
    updated = pipeline.run(_experience("User is a senior data scientist focused on NLP"))

    assert updated is not None
    assert updated.memory_id == original.memory_id
    assert updated.version == original.version + 1
    assert updated.content == "User is a senior data scientist focused on NLP"
    assert pipeline.knowledge_store.get(original.memory_id) == updated


def test_contradicting_fact_supersedes_existing_memory(pipeline: Pipeline):
    old = pipeline.run(_experience("Team uses Redis for the message queue"))
    new = pipeline.run(_experience("Team uses RabbitMQ for the message queue"))

    assert new is not None
    assert new.memory_id != old.memory_id
    assert new.content == "Team uses RabbitMQ for the message queue"

    stale = pipeline.knowledge_store.get(old.memory_id)
    assert stale.superseded_by == new.memory_id

    # search no longer surfaces the superseded memory as evidence
    results = pipeline.knowledge_store.search("message queue")
    assert old.memory_id not in [m.memory_id for m in results]


def test_irrelevant_content_produces_no_candidate_and_no_memory(pipeline: Pipeline):
    memory = pipeline.run(_experience("okay thanks"))

    assert memory is None
    assert pipeline.knowledge_store.search("okay thanks") == []
