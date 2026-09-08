from enum import Enum

from domain.enums.event_type import EventType

DEFAULT_MEMORY_COUNT_THRESHOLD = 3

# Event types that mark a natural point to consider consolidating —
# mirrors core/checkpoints/triggers.py's DEFAULT_CHECKPOINT_TRIGGERS,
# since "worth checkpointing" and "worth consolidating" are both tied to
# the same lifecycle boundaries.
DEFAULT_MILESTONE_TRIGGERS = frozenset(
    {
        EventType.TASK_COMPLETED,
        EventType.AGENT_HANDOFF,
        EventType.DECISION_CONFIRMED,
    }
)


class ConsolidationTrigger(str, Enum):
    """Why a consolidation pass was run."""

    TOPIC_THRESHOLD = "topic_threshold"  # enough related memories on one topic
    MEMORY_COUNT = "memory_count"  # total memory count in scope crossed a threshold
    MILESTONE = "milestone"  # a project milestone event occurred
    SESSION_COMPLETE = "session_complete"  # session/task lifecycle ended
    MANUAL = "manual"  # explicit user/operator request


def should_consolidate_topic(memory_count: int, threshold: int = DEFAULT_MEMORY_COUNT_THRESHOLD) -> bool:
    """True once a cluster of related memories is large enough to be
    worth consolidating into one durable statement."""
    return memory_count >= threshold


def is_milestone_event(event_type: EventType, triggers: frozenset[EventType] = DEFAULT_MILESTONE_TRIGGERS) -> bool:
    return event_type in triggers
