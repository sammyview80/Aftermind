from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.enums.event_type import EventType
from domain.enums.experience_outcome import ExperienceOutcome
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.scope import MemoryScope


def make_events():
    return [
        Event(event_type=EventType.USER_MESSAGE, payload={"text": "Build the login flow"}),
        Event(event_type=EventType.TOOL_STARTED, payload={"tool": "repo_search"}),
        Event(event_type=EventType.TOOL_COMPLETED, payload={"result": "found auth module"}),
        Event(event_type=EventType.AGENT_MESSAGE, payload={"text": "Login flow implemented"}),
        Event(event_type=EventType.TASK_COMPLETED, payload={"result": "tests passed"}),
    ]


def test_defaults_generate_id_and_created_at():
    experience = Experience()
    assert experience.experience_id
    assert isinstance(experience.created_at, datetime)
    assert experience.created_at.tzinfo == timezone.utc


def test_assembles_events_into_experience():
    events = make_events()
    scope = MemoryScope.of(tenant_id="t1")
    experience = Experience(
        scope=scope,
        events=events,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ended_at=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc),
        input="Build the login flow",
        output="Login flow implemented",
        outcome=ExperienceOutcome.SUCCESS,
        success=True,
        metadata={"actions": "searched repo, edited auth"},
    )

    assert experience.scope is scope
    assert experience.events == tuple(events)
    assert experience.input == "Build the login flow"
    assert experience.output == "Login flow implemented"
    assert experience.outcome == ExperienceOutcome.SUCCESS
    assert experience.success is True
    assert experience.metadata == {"actions": "searched repo, edited auth"}


def test_events_defaults_to_empty_tuple():
    experience = Experience()
    assert experience.events == ()


def test_events_stored_as_immutable_tuple():
    events = make_events()
    experience = Experience(events=events)
    assert isinstance(experience.events, tuple)
    events.append(Event())  # mutate original list after construction
    assert len(experience.events) == 5


def test_metadata_is_immutable_mapping():
    experience = Experience(metadata={"k": "v"})
    assert isinstance(experience.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        experience.metadata["k"] = "changed"


def test_experience_is_frozen():
    experience = Experience()
    with pytest.raises(Exception):
        experience.output = "changed"


@pytest.mark.parametrize(
    "outcome",
    [
        ExperienceOutcome.SUCCESS,
        ExperienceOutcome.FAILURE,
        ExperienceOutcome.PARTIAL,
        ExperienceOutcome.UNKNOWN,
    ],
)
def test_every_outcome_constructs(outcome):
    experience = Experience(outcome=outcome)
    assert experience.outcome == outcome
    assert experience.outcome == outcome.value


def test_outcome_and_success_default_to_unknown_and_none():
    experience = Experience()
    assert experience.outcome == ExperienceOutcome.UNKNOWN
    assert experience.success is None
