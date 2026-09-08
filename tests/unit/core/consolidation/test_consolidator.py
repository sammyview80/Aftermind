import json

from core.consolidation.consolidator import LLMConsolidator
from core.consolidation.planner import ConsolidationPlan
from core.consolidation.triggers import ConsolidationTrigger
from domain.models.consolidation_candidate import ConsolidationCandidate
from domain.models.consolidation_result import ConsolidationResult
from domain.models.knowledge_document import KnowledgeDocument, KnowledgeSection
from domain.models.memory import Memory
from domain.models.scope import MemoryScope


class ScriptedLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class FakeDocumentStore:
    def __init__(self) -> None:
        self._docs: dict[str, KnowledgeDocument] = {}

    def get(self, slug, scope=None):
        return self._docs.get(slug)

    def save(self, document):
        self._docs[document.slug] = document
        return document

    def search(self, query, scope=None, limit=5):
        return []


def _plan(memories, trigger=ConsolidationTrigger.TOPIC_THRESHOLD, scope=None) -> ConsolidationPlan:
    return ConsolidationPlan(scope=scope, topic="client preference", memories=tuple(memories), trigger=trigger)


def test_consolidate_maps_llm_response_to_candidate():
    response = json.dumps(
        {
            "content": "Client prefers premium dark visual styles, especially black and gold.",
            "confidence": 0.85,
            "reasoning": "All three memories describe the client's visual style preference.",
        }
    )
    memories = [
        Memory(memory_id="m1", content="Client rejected bright blue."),
        Memory(memory_id="m2", content="Client prefers dark layouts."),
        Memory(memory_id="m3", content="Client approved black and gold."),
    ]
    consolidator = LLMConsolidator(ScriptedLLM(response))

    candidate = consolidator.consolidate(_plan(memories))

    assert candidate.proposed_content == "Client prefers premium dark visual styles, especially black and gold."
    assert candidate.confidence == 0.85
    assert candidate.topic == "client preference"
    assert candidate.source_memory_ids == ("m1", "m2", "m3")
    assert candidate.trigger_reason == "topic_threshold"


def test_build_prompt_prefixes_system_prompt_when_given():
    consolidator = LLMConsolidator(ScriptedLLM("{}"), system_prompt="# Aftermind Memory Consolidator")
    prompt = consolidator.build_prompt(_plan([Memory(content="x")]))
    assert prompt.startswith("# Aftermind Memory Consolidator")


def test_apply_creates_new_document_when_none_exists():
    scope = MemoryScope.of(tenant_id="t1")
    candidate = ConsolidationCandidate(
        scope=scope,
        topic="client preference",
        source_memory_ids=("m1", "m2", "m3"),
        proposed_content="Client prefers premium dark visual styles, especially black and gold.",
        confidence=0.85,
    )
    result = ConsolidationResult(candidate_id=candidate.candidate_id, accepted=True, source_memory_ids=candidate.source_memory_ids)
    store = FakeDocumentStore()

    final = LLMConsolidator(ScriptedLLM("{}")).apply(candidate, result, store, slug="client-prefs", title="Client Preferences")

    assert final.accepted is True
    assert final.document_slug == "client-prefs"
    document = store.get("client-prefs")
    assert document.sections == (KnowledgeSection(heading="client preference", body=candidate.proposed_content),)
    assert document.source_memory_ids == ("m1", "m2", "m3")


def test_apply_merges_into_existing_document_by_topic():
    scope = MemoryScope.of(tenant_id="t1")
    store = FakeDocumentStore()
    store.save(
        KnowledgeDocument(
            scope=scope,
            slug="client-prefs",
            title="Client Preferences",
            sections=(KnowledgeSection(heading="client preference", body="old summary"),),
            source_memory_ids=("m1",),
        )
    )
    candidate = ConsolidationCandidate(
        scope=scope,
        topic="client preference",
        source_memory_ids=("m1", "m2", "m3"),
        proposed_content="new consolidated summary",
        confidence=0.9,
    )
    result = ConsolidationResult(candidate_id=candidate.candidate_id, accepted=True, source_memory_ids=candidate.source_memory_ids)

    LLMConsolidator(ScriptedLLM("{}")).apply(candidate, result, store, slug="client-prefs", title="Client Preferences")

    document = store.get("client-prefs")
    assert len(document.sections) == 1
    assert document.sections[0].body == "new consolidated summary"
    assert document.source_memory_ids == ("m1", "m2", "m3")


def test_apply_adds_new_section_for_a_different_topic():
    scope = MemoryScope.of(tenant_id="t1")
    store = FakeDocumentStore()
    store.save(
        KnowledgeDocument(
            scope=scope, slug="doc", title="Doc",
            sections=(KnowledgeSection(heading="topic a", body="a"),),
            source_memory_ids=("m1",),
        )
    )
    candidate = ConsolidationCandidate(scope=scope, topic="topic b", source_memory_ids=("m2", "m3"), proposed_content="b")
    result = ConsolidationResult(candidate_id=candidate.candidate_id, accepted=True, source_memory_ids=candidate.source_memory_ids)

    LLMConsolidator(ScriptedLLM("{}")).apply(candidate, result, store, slug="doc", title="Doc")

    document = store.get("doc")
    assert {s.heading for s in document.sections} == {"topic a", "topic b"}
    assert document.source_memory_ids == ("m1", "m2", "m3")


def test_apply_is_a_noop_when_result_not_accepted():
    store = FakeDocumentStore()
    candidate = ConsolidationCandidate(topic="x", proposed_content="y")
    rejected = ConsolidationResult(candidate_id=candidate.candidate_id, accepted=False, reasoning="rejected: low confidence")

    final = LLMConsolidator(ScriptedLLM("{}")).apply(candidate, rejected, store, slug="doc", title="Doc")

    assert final is rejected
    assert store.get("doc") is None
