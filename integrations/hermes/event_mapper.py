from domain.enums.event_type import EventType
from domain.models.event import Event

"""Maps Hermes' native event shape onto Aftermind's Event.

Assumed Hermes event shape (adjust HERMES_EVENT_TYPE_MAP/field names
here if Hermes' actual schema differs — this is the single seam):

    {
        "id": "evt_123",
        "type": "user_message" | "agent_message" | "tool_call" | "tool_result" |
                "task_start" | "task_end" | "handoff" | "correction" | "decision",
        "text": "...",           # for message/correction/decision events
        "tool": "...",           # for tool_call/tool_result
        "result": "...",         # for tool_result
        "error": "...",          # for a failed tool_result/task_end
        "success": true/false,   # for task_end
        "timestamp": "2026-...", # ISO 8601
    }
"""

HERMES_EVENT_TYPE_MAP: dict[str, EventType] = {
    "user_message": EventType.USER_MESSAGE,
    "agent_message": EventType.AGENT_MESSAGE,
    "tool_call": EventType.TOOL_STARTED,
    "tool_result": EventType.TOOL_COMPLETED,  # refined to TOOL_FAILED below if it carries an error
    "task_start": EventType.TASK_STARTED,
    "task_end": EventType.TASK_COMPLETED,  # refined to TASK_FAILED below if success is False
    "handoff": EventType.AGENT_HANDOFF,
    "correction": EventType.USER_CORRECTION,
    "decision": EventType.DECISION_CONFIRMED,
}


def map_hermes_event(hermes_event: dict) -> Event:
    """Convert one raw Hermes event into a normalized Event. Unknown
    Hermes event types fall back to AGENT_MESSAGE rather than raising —
    this is an ingestion boundary, not a place to reject unfamiliar
    input outright."""
    hermes_type = hermes_event.get("type", "")
    event_type = HERMES_EVENT_TYPE_MAP.get(hermes_type, EventType.AGENT_MESSAGE)

    if hermes_type == "tool_result" and hermes_event.get("error"):
        event_type = EventType.TOOL_FAILED
    if hermes_type == "task_end" and hermes_event.get("success") is False:
        event_type = EventType.TASK_FAILED

    payload = {
        key: hermes_event[key]
        for key in ("text", "tool", "result", "error", "success")
        if key in hermes_event
    }

    kwargs = {"event_type": event_type, "payload": payload, "source": "hermes"}
    if hermes_event.get("id"):
        kwargs["event_id"] = hermes_event["id"]
    return Event(**kwargs)
