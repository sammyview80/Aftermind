from enum import Enum


class EventType(str, Enum):
    """Normalized event types. Every framework adapter (Hermes, Claude
    Code, Codex, LangGraph, ...) maps its native event vocabulary onto
    this fixed set — Event itself stays framework-neutral."""

    USER_MESSAGE = "user_message"
    AGENT_MESSAGE = "agent_message"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    TOOL_FAILED = "tool_failed"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    AGENT_HANDOFF = "agent_handoff"
    USER_CORRECTION = "user_correction"
    DECISION_CONFIRMED = "decision_confirmed"
