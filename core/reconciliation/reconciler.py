from dataclasses import replace
from datetime import datetime, timezone

from core.json_utils import parse_json_response
from domain.enums.reconciliation_action import ReconciliationAction
from domain.interfaces.knowledge_store import KnowledgeStore
from domain.interfaces.llm_provider import LLMProvider
from domain.models.candidate import Candidate
from domain.models.memory import Memory
from domain.models.memory_decision import MemoryDecision

_PROMPT_TEMPLATE = """You are a memory reconciliation engine. Decide how to reconcile the \
new candidate memory against existing memories for the same scope.

CANDIDATE:
{candidate_content}

EXISTING MEMORIES:
{evidence_block}

Respond with a single JSON object:
{{"action": "ignore|create|update|merge|supersede", "target_memory_id": "<id or null>", \
"confidence": <0-1>, "reasoning": "<one sentence>"}}

- "ignore": candidate adds nothing beyond an existing memory.
- "create": no existing memory relates to this candidate.
- "update": an existing memory is still correct but the candidate adds detail to it.
- "merge": the candidate and an existing memory should be combined into one.
- "supersede": the candidate contradicts an existing memory, which is now outdated.

Respond with ONLY that JSON object — no prose, no markdown code fences.
"""


class Reconciler:
    """Decides, with LLM assistance, how a candidate relates to existing
    memory — and applies that decision to the knowledge store."""

    def __init__(self, llm_provider: LLMProvider, system_prompt: str = "") -> None:
        self._llm = llm_provider
        self._system_prompt = system_prompt

    def build_prompt(self, candidate: Candidate, evidence: list[Memory]) -> str:
        if evidence:
            evidence_block = "\n".join(f"{i}. [{m.memory_id}] {m.content}" for i, m in enumerate(evidence, start=1))
        else:
            evidence_block = "None found."
        task = _PROMPT_TEMPLATE.format(candidate_content=candidate.content, evidence_block=evidence_block)
        return f"{self._system_prompt}\n\n{task}" if self._system_prompt else task

    def reconcile(self, candidate: Candidate, evidence: list[Memory]) -> MemoryDecision:
        prompt = self.build_prompt(candidate, evidence)
        raw = self._llm.complete(prompt)
        parsed = parse_json_response(raw)

        return MemoryDecision(
            candidate_id=candidate.candidate_id,
            action=ReconciliationAction(parsed["action"]),
            target_memory_id=parsed.get("target_memory_id"),
            evidence_memory_ids=tuple(m.memory_id for m in evidence),
            confidence=float(parsed.get("confidence", 0.0)),
            reasoning=parsed.get("reasoning", ""),
        )

    def apply(
        self, decision: MemoryDecision, candidate: Candidate, knowledge_store: KnowledgeStore
    ) -> Memory | None:
        """Carry out an approved decision against the knowledge store."""
        if decision.action == ReconciliationAction.IGNORE:
            return None

        if decision.action == ReconciliationAction.CREATE or decision.target_memory_id is None:
            memory = Memory(
                # Durable memory outlives the run/session it was learned
                # in — strip execution-identity scope levels so it's
                # findable from a later session, not just this one.
                scope=candidate.scope.stable() if candidate.scope else None,
                content=candidate.content,
                memory_type=candidate.memory_type,
                memory_domain=candidate.memory_domain,
                entities=candidate.entities,
                relationships=candidate.relationships,
                confidence=decision.confidence,
                source_candidate_ids=(candidate.candidate_id,),
            )
            return knowledge_store.save(memory)

        target = knowledge_store.get(decision.target_memory_id)
        if target is None:
            # Evidence referenced a memory that no longer exists; fall back
            # to creating a fresh one rather than silently dropping content.
            return self.apply(replace(decision, action=ReconciliationAction.CREATE), candidate, knowledge_store)

        now = datetime.now(timezone.utc)

        if decision.action == ReconciliationAction.UPDATE:
            updated = replace(
                target,
                content=candidate.content,
                confidence=max(target.confidence, decision.confidence),
                version=target.version + 1,
                source_candidate_ids=target.source_candidate_ids + (candidate.candidate_id,),
                updated_at=now,
            )
            return knowledge_store.save(updated)

        if decision.action == ReconciliationAction.MERGE:
            merged = replace(
                target,
                content=f"{target.content}; {candidate.content}",
                confidence=max(target.confidence, decision.confidence),
                version=target.version + 1,
                source_candidate_ids=target.source_candidate_ids + (candidate.candidate_id,),
                updated_at=now,
            )
            return knowledge_store.save(merged)

        if decision.action == ReconciliationAction.SUPERSEDE:
            successor = Memory(
                scope=candidate.scope.stable() if candidate.scope else None,
                content=candidate.content,
                memory_type=candidate.memory_type,
                memory_domain=candidate.memory_domain,
                entities=candidate.entities,
                relationships=candidate.relationships,
                confidence=decision.confidence,
                version=target.version + 1,
                source_candidate_ids=(candidate.candidate_id,),
            )
            saved_successor = knowledge_store.save(successor)
            knowledge_store.save(replace(target, superseded_by=saved_successor.memory_id, updated_at=now))
            return saved_successor

        raise ValueError(f"unhandled reconciliation action: {decision.action!r}")
