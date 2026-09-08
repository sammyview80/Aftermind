from dataclasses import replace
from typing import Optional

from core.consolidation.planner import ConsolidationPlan
from core.json_utils import parse_json_response
from domain.interfaces.document_store import DocumentStore
from domain.interfaces.llm_provider import LLMProvider
from domain.models.consolidation_candidate import ConsolidationCandidate
from domain.models.consolidation_result import ConsolidationResult
from domain.models.knowledge_document import KnowledgeDocument, KnowledgeSection

_PROMPT_TEMPLATE = """MEMORIES TO CONSOLIDATE (trigger: {trigger}, topic: {topic}):
{memories_block}

Return a single JSON object:
{{"content": "...", "confidence": <0-1>, "reasoning": "<one sentence>"}}

Respond with ONLY that JSON object — no prose, no markdown code fences.
"""


class LLMConsolidator:
    """Synthesizes a cluster of related memories (a ConsolidationPlan)
    into one durable ConsolidationCandidate, and — once validated —
    applies it into OpenKnowledge without ever touching the source
    memories."""

    def __init__(self, llm_provider: LLMProvider, system_prompt: str = "") -> None:
        self._llm = llm_provider
        self._system_prompt = system_prompt

    def build_prompt(self, plan: ConsolidationPlan) -> str:
        memories_block = "\n".join(f"{i}. {m.content}" for i, m in enumerate(plan.memories, start=1))
        task = _PROMPT_TEMPLATE.format(trigger=plan.trigger.value, topic=plan.topic, memories_block=memories_block)
        return f"{self._system_prompt}\n\n{task}" if self._system_prompt else task

    def consolidate(self, plan: ConsolidationPlan) -> ConsolidationCandidate:
        raw = self._llm.complete(self.build_prompt(plan))
        parsed = parse_json_response(raw)

        return ConsolidationCandidate(
            scope=plan.scope,
            topic=plan.topic,
            source_memory_ids=tuple(m.memory_id for m in plan.memories),
            proposed_content=parsed["content"],
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning=parsed.get("reasoning", ""),
            trigger_reason=plan.trigger.value,
        )

    def apply(
        self,
        candidate: ConsolidationCandidate,
        result: ConsolidationResult,
        document_store: DocumentStore,
        slug: str,
        title: str,
    ) -> ConsolidationResult:
        """Write a validator-accepted candidate into OpenKnowledge,
        merging into an existing document's section by topic if one
        exists, and preserving provenance (`source_memory_ids`) — never
        deleting or rewriting the source memories themselves. Extends
        `result` (from ConsolidationValidator.validate) with the
        resulting document's id/slug rather than minting a disconnected
        second result."""
        if not result.accepted:
            return result

        existing = document_store.get(slug, scope=candidate.scope)

        if existing is None:
            document = KnowledgeDocument(
                scope=candidate.scope,
                slug=slug,
                title=title,
                sections=(KnowledgeSection(heading=candidate.topic, body=candidate.proposed_content),),
                source_memory_ids=candidate.source_memory_ids,
            )
        else:
            sections = list(existing.sections)
            matched = next((i for i, s in enumerate(sections) if s.heading == candidate.topic), None)
            if matched is not None:
                sections[matched] = KnowledgeSection(heading=candidate.topic, body=candidate.proposed_content)
            else:
                sections.append(KnowledgeSection(heading=candidate.topic, body=candidate.proposed_content))

            merged_source_ids = tuple(dict.fromkeys(existing.source_memory_ids + candidate.source_memory_ids))
            document = replace(existing, sections=tuple(sections), source_memory_ids=merged_source_ids)

        saved = document_store.save(document)

        return replace(result, document_id=saved.document_id, document_slug=saved.slug)
