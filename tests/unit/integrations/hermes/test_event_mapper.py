from domain.enums.event_type import EventType
from integrations.hermes.event_mapper import map_hermes_event


def test_maps_known_types():
    assert map_hermes_event({"type": "user_message", "text": "hi"}).event_type == EventType.USER_MESSAGE
    assert map_hermes_event({"type": "task_start"}).event_type == EventType.TASK_STARTED
    assert map_hermes_event({"type": "handoff"}).event_type == EventType.AGENT_HANDOFF


def test_tool_result_with_error_maps_to_tool_failed():
    event = map_hermes_event({"type": "tool_result", "tool": "repo_search", "error": "timeout"})
    assert event.event_type == EventType.TOOL_FAILED
    assert event.payload["error"] == "timeout"


def test_tool_result_without_error_maps_to_tool_completed():
    event = map_hermes_event({"type": "tool_result", "result": "found it"})
    assert event.event_type == EventType.TOOL_COMPLETED


def test_task_end_with_success_false_maps_to_task_failed():
    event = map_hermes_event({"type": "task_end", "success": False})
    assert event.event_type == EventType.TASK_FAILED


def test_task_end_with_success_true_maps_to_task_completed():
    event = map_hermes_event({"type": "task_end", "success": True})
    assert event.event_type == EventType.TASK_COMPLETED


def test_unknown_type_falls_back_to_agent_message():
    assert map_hermes_event({"type": "something_new"}).event_type == EventType.AGENT_MESSAGE


def test_preserves_id_and_source():
    event = map_hermes_event({"id": "evt_1", "type": "user_message", "text": "hi"})
    assert event.event_id == "evt_1"
    assert event.source == "hermes"
