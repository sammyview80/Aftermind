from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.enums.event_type import EventType
from domain.models.event import Event
from domain.models.scope import MemoryScope


def test_defaults_generate_id_and_timestamp():
    event = Event()
    assert event.event_id
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo == timezone.utc


def test_construct_with_all_fields():
    scope = MemoryScope.of(tenant_id="t1")
    ts = datetime.now(timezone.utc)
    event = Event(
        event_id="e1",
        event_type=EventType.TOOL_STARTED,
        timestamp=ts,
        scope=scope,
        payload={"tool": "search"},
        source="langgraph",
        metadata={"trace_id": "tr1"},
    )
    assert event.event_id == "e1"
    assert event.event_type == EventType.TOOL_STARTED
    assert event.timestamp == ts
    assert event.scope is scope
    assert event.payload == {"tool": "search"}
    assert event.source == "langgraph"
    assert event.metadata == {"trace_id": "tr1"}


@pytest.mark.parametrize(
    "event_type",
    [
        EventType.USER_MESSAGE,
        EventType.AGENT_MESSAGE,
        EventType.TOOL_STARTED,
        EventType.TOOL_COMPLETED,
        EventType.TOOL_FAILED,
        EventType.TASK_STARTED,
        EventType.TASK_COMPLETED,
        EventType.TASK_FAILED,
        EventType.AGENT_HANDOFF,
        EventType.USER_CORRECTION,
        EventType.DECISION_CONFIRMED,
    ],
)
def test_every_event_type_constructs(event_type):
    event = Event(event_type=event_type)
    assert event.event_type == event_type
    assert event.event_type == event_type.value  # str enum, comparable to plain string


def test_payload_and_metadata_are_immutable_mappings():
    event = Event(payload={"k": "v"}, metadata={"m": "1"})
    assert isinstance(event.payload, MappingProxyType)
    assert isinstance(event.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        event.payload["k"] = "changed"
    with pytest.raises(TypeError):
        event.metadata["m"] = "changed"


def test_event_is_frozen():
    event = Event()
    with pytest.raises(Exception):
        event.source = "codex"


def test_payload_copy_isolated_from_source_dict():
    source_dict = {"k": "v"}
    event = Event(payload=source_dict)
    source_dict["k"] = "mutated"
    assert event.payload["k"] == "v"


def test_scope_defaults_to_none():
    event = Event()
    assert event.scope is None
