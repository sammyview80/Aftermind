import re

from core.json_utils import parse_json_response
from domain.enums.memory_type import MemoryType
from domain.interfaces.llm_provider import LLMProvider
from domain.models.candidate import Candidate
from domain.models.experience import Experience

# Content that carries no durable information — acknowledgements,
# filler — even though it's a perfectly normal turn in a conversation.
_TRIVIAL_PHRASES = {
    "ok",
    "okay",
    "ok thanks",
    "okay thanks",
    "thanks",
    "thank you",
    "got it",
    "sure",
    "sounds good",
    "no problem",
    "alright",
    "cool",
}


def _is_trivial(text: str) -> bool:
    normalized = text.strip().lower().rstrip(".!")
    return not normalized or normalized in _TRIVIAL_PHRASES


# "Codex here: we decided X" / "Hermes here — X" / "As Claude Code, I think X".
# A memory is recalled state, not a quoted voice: injected back into another
# agent's context, first-person framing from a *different* agent reads like
# prompt injection and gets flagged, even when the fact itself is fine.
# Strip the framing, keep the statement.
# Agent name = 1-3 Capitalized words ("Codex", "Claude Code", "Hermes Agent"),
# so ordinary sentences ("The config lives here: x") never match.
_AGENT_NAME = r"[A-Z][\w-]*(?:\s+[A-Z][\w-]*){0,2}"
_AGENT_FRAMING = re.compile(
    r"^\s*(?:\[[^\]]{1,40}\]\s*)?"  # optional [tag]
    rf"(?:(?:this is |it's |it is )?{_AGENT_NAME}\s+here(?:\s*(?:again|speaking))?"  # "Codex here", "Claude Code here again"
    rf"|As\s+{_AGENT_NAME})"  # "As Codex,"
    r"\s*[:,—–-]\s*",
)


def strip_agent_framing(text: str) -> str:
    stripped = _AGENT_FRAMING.sub("", text, count=1).strip()
    if not stripped:
        return text.strip()
    return stripped[0].upper() + stripped[1:] if stripped[0].islower() else stripped


class CandidateExtractor:
    """Pulls candidate memories out of an Experience.

    This stage only asks "is there any durable content here at all?" — it
    filters out pure noise (acknowledgements, empty turns) but does not
    score or judge worth beyond that. Scoring is the evaluator's job.
    """

    def extract(self, experience: Experience) -> list[Candidate]:
        text = strip_agent_framing((experience.output or experience.input or "").strip())
        if _is_trivial(text):
            return []

        return [
            Candidate(
                experience_id=experience.experience_id,
                scope=experience.scope,
                content=text,
                source_event_ids=tuple(event.event_id for event in experience.events),
            )
        ]


_EXTRACTOR_PROMPT_TEMPLATE = """EXPERIENCE:
input: {input}
output: {output}
events: {events}

Return a JSON array of candidates (empty array if nothing meaningful):
[{{"content": "...", "memory_type": "semantic|episodic|procedural", \
"entities": ["..."], "relationships": ["..."], "user_confirmed": true|false|null, \
"confidence": <0-1>}}]

Respond with ONLY that JSON array — no prose, no markdown code fences.
"""


class LLMCandidateExtractor:
    """LLM-backed candidate extraction using providers/llm/prompts/candidate_extractor.md
    as its instructions. Extraction stays advisory — the runtime (this
    class) still owns turning the model's proposals into Candidate
    objects; nothing here decides whether a candidate is worth keeping."""

    def __init__(self, llm_provider: LLMProvider, system_prompt: str = "") -> None:
        self._llm = llm_provider
        self._system_prompt = system_prompt

    def build_prompt(self, experience: Experience) -> str:
        task = _EXTRACTOR_PROMPT_TEMPLATE.format(
            input=experience.input,
            output=experience.output,
            events=[e.event_type.value for e in experience.events],
        )
        return f"{self._system_prompt}\n\n{task}" if self._system_prompt else task

    def extract(self, experience: Experience) -> list[Candidate]:
        raw = self._llm.complete(self.build_prompt(experience))
        proposals = parse_json_response(raw)

        return [
            Candidate(
                experience_id=experience.experience_id,
                scope=experience.scope,
                content=proposal["content"],
                memory_type=MemoryType(proposal.get("memory_type", MemoryType.SEMANTIC.value)),
                entities=tuple(proposal.get("entities", ())),
                relationships=tuple(proposal.get("relationships", ())),
                confidence=float(proposal.get("confidence", 0.0)),
                user_confirmed=proposal.get("user_confirmed"),
                source_event_ids=tuple(event.event_id for event in experience.events),
            )
            for proposal in proposals
        ]
