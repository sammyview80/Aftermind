"""End-to-end test of the consolidation engine:

    Stored memories -> ConsolidationTrigger -> ConsolidationPlanner
        -> LLMConsolidator -> ConsolidationValidator -> OpenKnowledge
        -> provenance links back to source memories

Matches the brief's example exactly:
    "Client rejected bright blue."
    "Client prefers dark layouts."
    "Client approved black + gold."
    -> "Client prefers premium dark visual styles, especially black and gold."

A ScriptedLLM stands in for the real model (deterministic, offline);
OpenKnowledgeStore is the real filesystem-backed implementation writing
to a tmp_path, not a fake — this is the actual durable-knowledge write
path.
"""
import json

from core.consolidation.consolidator import LLMConsolidator
from core.consolidation.planner import ConsolidationPlanner
from core.consolidation.triggers import ConsolidationTrigger, should_consolidate_topic
from core.consolidation.validator import ConsolidationValidator
from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from providers.llm.base import load_prompt
from providers.openknowledge.client import LocalMarkdownClient
from providers.openknowledge.store import OpenKnowledgeStore


class ScriptedLLM:
    def complete(self, prompt: str) -> str:
        return json.dumps(
            {
                "content": "Client prefers premium dark visual styles, especially black and gold.",
                "confidence": 0.9,
                "reasoning": "All three memories describe the client's reaction to visual styling choices.",
            }
        )


def test_related_memories_consolidate_into_durable_knowledge_with_provenance(tmp_path):
    scope = MemoryScope.of(tenant_id="t1", project_id="design-client")

    mem1 = Memory(scope=scope, content="Client rejected bright blue.")
    mem2 = Memory(scope=scope, content="Client prefers dark layouts.")
    mem3 = Memory(scope=scope, content="Client approved black and gold.")
    memories = [mem1, mem2, mem3]

    assert should_consolidate_topic(len(memories), threshold=3) is True

    planner = ConsolidationPlanner(min_group_size=3)
    plans = planner.plan(memories, ConsolidationTrigger.TOPIC_THRESHOLD, scope=scope)
    assert len(plans) == 1
    plan = plans[0]
    assert {m.memory_id for m in plan.memories} == {mem1.memory_id, mem2.memory_id, mem3.memory_id}

    consolidator = LLMConsolidator(ScriptedLLM(), system_prompt=load_prompt("consolidator"))
    candidate = consolidator.consolidate(plan)
    assert candidate.proposed_content == "Client prefers premium dark visual styles, especially black and gold."
    assert set(candidate.source_memory_ids) == {mem1.memory_id, mem2.memory_id, mem3.memory_id}

    validator = ConsolidationValidator()
    result = validator.validate(candidate)
    assert result.accepted is True

    document_store = OpenKnowledgeStore(LocalMarkdownClient(base_dir=tmp_path))
    final_result = consolidator.apply(
        candidate, result, document_store, slug="design-client-knowledge", title="Design Client Knowledge"
    )

    assert final_result.accepted is True
    assert final_result.document_slug == "design-client-knowledge"

    document = document_store.get("design-client-knowledge", scope=scope)
    markdown = document.to_markdown()
    assert "premium dark visual styles" in markdown
    assert "black and gold" in markdown

    # Provenance: knowledge links back to all three source memories —
    # and the source memories themselves were never touched.
    assert set(document.source_memory_ids) == {mem1.memory_id, mem2.memory_id, mem3.memory_id}
    assert mem1.content == "Client rejected bright blue."
    assert mem2.content == "Client prefers dark layouts."
    assert mem3.content == "Client approved black and gold."


def test_below_threshold_cluster_is_never_consolidated():
    scope = MemoryScope.of(tenant_id="t1")
    memories = [
        Memory(scope=scope, content="Client prefers dark layouts."),
        Memory(scope=scope, content="Client approved black and gold."),
    ]

    plans = ConsolidationPlanner(min_group_size=3).plan(memories, ConsolidationTrigger.TOPIC_THRESHOLD, scope=scope)

    assert plans == []


def test_low_confidence_proposal_is_rejected_and_never_written(tmp_path):
    scope = MemoryScope.of(tenant_id="t1")
    memories = [Memory(scope=scope, content=f"Client mentioned option {i}") for i in range(3)]
    plan = ConsolidationPlanner(min_group_size=3).plan(memories, ConsolidationTrigger.MANUAL, scope=scope)[0]

    class LowConfidenceLLM:
        def complete(self, prompt: str) -> str:
            return json.dumps({"content": "vague guess", "confidence": 0.1, "reasoning": "uncertain"})

    consolidator = LLMConsolidator(LowConfidenceLLM())
    candidate = consolidator.consolidate(plan)
    result = ConsolidationValidator(min_confidence=0.4).validate(candidate)

    assert result.accepted is False

    document_store = OpenKnowledgeStore(LocalMarkdownClient(base_dir=tmp_path))
    final_result = consolidator.apply(candidate, result, document_store, slug="doc", title="Doc")

    assert final_result.accepted is False
    assert document_store.get("doc", scope=scope) is None
