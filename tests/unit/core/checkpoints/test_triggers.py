from core.checkpoints.triggers import should_checkpoint
from domain.enums.event_type import EventType
from domain.models.event import Event
from domain.models.experience import Experience


def test_no_trigger_events_returns_false():
    experience = Experience(events=[Event(event_type=EventType.USER_MESSAGE), Event(event_type=EventType.AGENT_MESSAGE)])
    assert should_checkpoint(experience) is False


def test_task_completed_triggers_checkpoint():
    experience = Experience(events=[Event(event_type=EventType.TASK_COMPLETED)])
    assert should_checkpoint(experience) is True


def test_custom_trigger_set_is_respected():
    experience = Experience(events=[Event(event_type=EventType.USER_CORRECTION)])
    assert should_checkpoint(experience) is False
    assert should_checkpoint(experience, triggers=frozenset({EventType.USER_CORRECTION})) is True


def test_no_events_returns_false():
    assert should_checkpoint(Experience(events=[])) is False
