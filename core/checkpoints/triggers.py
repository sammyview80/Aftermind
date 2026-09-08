from domain.enums.event_type import EventType
from domain.models.experience import Experience

# Event types that mark a natural stopping point — the point at which an
# agent's work is done enough (or stuck enough) to be worth resuming from
# later, rather than replaying from scratch.
DEFAULT_CHECKPOINT_TRIGGERS = frozenset(
    {
        EventType.TASK_COMPLETED,
        EventType.TASK_FAILED,
        EventType.AGENT_HANDOFF,
    }
)


def should_checkpoint(
    experience: Experience, triggers: frozenset[EventType] = DEFAULT_CHECKPOINT_TRIGGERS
) -> bool:
    """True if this experience contains an event that should cause a
    checkpoint to be created once it finishes processing."""
    return any(event.event_type in triggers for event in experience.events)
