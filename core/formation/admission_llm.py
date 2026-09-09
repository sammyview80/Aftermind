"""Semantic memory admission with one LLM call.

The deterministic gate (admission.py) removes noise cheaply. What is
left is prose that *might* hold something durable — often a long
assistant message with one decision buried in it, or a user message
mixing a request with a fact. This stage asks the model to extract the
memory-worthy atomic statements (with type, entities, relationships and
a usefulness score) or return nothing. Its output is not trusted
blindly: every proposal is run back through the gate and the score
threshold before it becomes a Candidate.
"""
import logging
from dataclasses import replace

from core.formation.admission import gate, redact_secrets
from core.formation.domain_classifier import classify_domain
from core.json_utils import parse_json_response
from domain.enums.memory_type import MemoryType
from domain.interfaces.llm_provider import LLMProvider
from domain.models.candidate import Candidate
from domain.models.experience import Experience

_LOG = logging.getLogger("aftermind.formation")

_PROMPT_TEMPLATE = """ADMISSION REVIEW
speaker: {speaker}
events: {events}

TEXT:
{text}

Return a JSON array of memory-worthy statements (empty array if nothing is worth
remembering across sessions):
[{{"content": "<one atomic, self-contained statement in third person, present tense>",
  "memory_type": "semantic|episodic|procedural",
  "entities": ["..."], "relationships": ["<Subject> <relation> <Object>"],
  "usefulness": <0-1>, "durability": <0-1>, "confidence": <0-1>,
  "user_confirmed": true|false|null, "reasoning": "<one short sentence>"}}]

Respond with ONLY that JSON array — no prose, no markdown code fences.
"""


class LLMAdmission:
    def __init__(self, llm_provider: LLMProvider, system_prompt: str = "", min_score: float = 0.5) -> None:
        self._llm = llm_provider
        self._system_prompt = system_prompt
        self.min_score = min_score

    @staticmethod
    def _speaker(experience: Experience) -> str:
        types = {e.event_type.value for e in experience.events}
        if "user_message" in types or "user_correction" in types:
            return "user"
        if types & {"tool_failed", "task_failed", "tool_completed"}:
            return "tool"
        return "assistant"

    def build_prompt(self, experience: Experience) -> str:
        text = redact_secrets(experience.output or experience.input or "")
        task = _PROMPT_TEMPLATE.format(
            speaker=self._speaker(experience),
            events=[e.event_type.value for e in experience.events],
            text=text[:6000],
        )
        return f"{self._system_prompt}\n\n{task}" if self._system_prompt else task

    def extract(self, experience: Experience) -> list[Candidate]:
        raw = self._llm.complete(self.build_prompt(experience))
        proposals = parse_json_response(raw)
        if isinstance(proposals, dict):
            proposals = proposals.get("memories") or proposals.get("candidates") or []
        if not isinstance(proposals, list):
            return []

        candidates: list[Candidate] = []
        for proposal in proposals:
            if not isinstance(proposal, dict):
                continue
            content = str(proposal.get("content", "")).strip()
            decision = gate(content)
            if not decision.admitted or decision.needs_extraction:
                _LOG.debug("admission: dropped LLM proposal (%s): %r", decision.reason, content[:80])
                continue
            usefulness = _score(proposal.get("usefulness"))
            durability = _score(proposal.get("durability"))
            confidence = _score(proposal.get("confidence"), default=0.7)
            # Both must clear the bar: a useful-but-transient status ("build
            # is running") is exactly what must not become long-term memory.
            if min(usefulness, durability) < self.min_score:
                _LOG.debug("admission: below score bar: %r", content[:80])
                continue
            try:
                memory_type = MemoryType(str(proposal.get("memory_type", "semantic")).lower())
            except ValueError:
                memory_type = MemoryType.SEMANTIC
            candidates.append(
                Candidate(
                    experience_id=experience.experience_id,
                    scope=experience.scope,
                    content=content,
                    memory_type=memory_type,
                    memory_domain=classify_domain(content),
                    entities=tuple(str(e) for e in proposal.get("entities", ()) if e),
                    relationships=tuple(str(r) for r in proposal.get("relationships", ()) if r),
                    confidence=confidence,
                    future_usefulness=usefulness,
                    durability=durability,
                    novelty=0.6,
                    impact=usefulness,
                    specificity=0.8,
                    user_confirmed=proposal.get("user_confirmed"),
                    source_event_ids=tuple(event.event_id for event in experience.events),
                    metadata={"admission": "llm", "reasoning": str(proposal.get("reasoning", ""))[:200]},
                )
            )
        return candidates


def _score(value, default: float = 0.0) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def with_default_scores(candidate: Candidate) -> Candidate:
    """Rule-based fallback scoring for a gate-admitted candidate when no
    LLM is configured."""
    return replace(
        candidate,
        confidence=candidate.confidence or 0.8,
        future_usefulness=candidate.future_usefulness or 0.7,
        durability=candidate.durability or 0.7,
        novelty=candidate.novelty or 0.6,
        impact=candidate.impact or 0.6,
        specificity=candidate.specificity or 0.8,
    )
