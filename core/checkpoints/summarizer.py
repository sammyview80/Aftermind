from dataclasses import dataclass, field

from core.json_utils import parse_json_response
from domain.enums.event_type import EventType
from domain.interfaces.llm_provider import LLMProvider
from domain.models.experience import Experience

_COMPLETED_TYPES = frozenset({EventType.TOOL_COMPLETED, EventType.TASK_COMPLETED})
_BLOCKED_TYPES = frozenset({EventType.TOOL_FAILED, EventType.TASK_FAILED})


@dataclass(frozen=True)
class CheckpointSummary:
    """Structured breakdown of an experience, ready to be persisted as a
    Checkpoint. An intermediate value, not a stored contract — the
    Checkpoint model is what gets persisted."""

    goal: str = ""
    completed: tuple[str, ...] = field(default_factory=tuple)
    current: str = ""
    blockers: tuple[str, ...] = field(default_factory=tuple)
    next_steps: tuple[str, ...] = field(default_factory=tuple)


def _event_text(event) -> str:
    payload = event.payload
    return str(payload.get("text") or payload.get("result") or payload.get("error") or "")


class CheckpointSummarizer:
    """Turns an Experience's raw events into the goal/completed/current/
    blockers/next shape a checkpoint is built from."""

    def summarize(self, experience: Experience) -> CheckpointSummary:
        goal = next(
            (_event_text(e) for e in experience.events if e.event_type == EventType.USER_MESSAGE),
            experience.input,
        )

        completed = tuple(
            text for e in experience.events if e.event_type in _COMPLETED_TYPES and (text := _event_text(e))
        )

        current = next(
            (_event_text(e) for e in reversed(experience.events) if e.event_type == EventType.AGENT_MESSAGE),
            experience.output,
        )

        blockers = tuple(
            text for e in experience.events if e.event_type in _BLOCKED_TYPES and (text := _event_text(e))
        )

        next_steps = tuple(experience.metadata.get("next_steps", ()))

        return CheckpointSummary(
            goal=goal,
            completed=completed,
            current=current,
            blockers=blockers,
            next_steps=next_steps,
        )


_SUMMARIZER_PROMPT_TEMPLATE = """PREVIOUS CHECKPOINT: {previous_goal}

EXPERIENCE:
input: {input}
output: {output}
events: {events}

Return a single JSON object:
{{"goal": "...", "completed": ["..."], "current": "...", "blocked_by": ["..."], "next_steps": ["..."]}}
"""


class LLMCheckpointSummarizer:
    """LLM-backed summarization using providers/llm/prompts/checkpoint.md
    as its instructions, for cases where rule-based extraction from
    typed events (CheckpointSummarizer) misses nuance in free-form
    conversation."""

    def __init__(self, llm_provider: LLMProvider, system_prompt: str = "") -> None:
        self._llm = llm_provider
        self._system_prompt = system_prompt

    def build_prompt(self, experience: Experience, previous_goal: str = "") -> str:
        task = _SUMMARIZER_PROMPT_TEMPLATE.format(
            previous_goal=previous_goal or "None.",
            input=experience.input,
            output=experience.output,
            events=[e.event_type.value for e in experience.events],
        )
        return f"{self._system_prompt}\n\n{task}" if self._system_prompt else task

    def summarize(self, experience: Experience, previous_goal: str = "") -> CheckpointSummary:
        raw = self._llm.complete(self.build_prompt(experience, previous_goal))
        parsed = parse_json_response(raw)

        return CheckpointSummary(
            goal=parsed.get("goal", ""),
            completed=tuple(parsed.get("completed", ())),
            current=parsed.get("current", ""),
            blockers=tuple(parsed.get("blocked_by", ())),
            next_steps=tuple(parsed.get("next_steps", ())),
        )
