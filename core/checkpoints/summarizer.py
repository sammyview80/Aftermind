from dataclasses import dataclass, field

from domain.enums.event_type import EventType
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
