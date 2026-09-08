from core.consolidation.triggers import (
    ConsolidationTrigger,
    is_milestone_event,
    should_consolidate_topic,
)
from domain.enums.event_type import EventType


def test_should_consolidate_topic_below_threshold():
    assert should_consolidate_topic(2, threshold=3) is False


def test_should_consolidate_topic_at_threshold():
    assert should_consolidate_topic(3, threshold=3) is True


def test_is_milestone_event_true_for_task_completed():
    assert is_milestone_event(EventType.TASK_COMPLETED) is True


def test_is_milestone_event_false_for_user_message():
    assert is_milestone_event(EventType.USER_MESSAGE) is False


def test_is_milestone_event_respects_custom_triggers():
    assert is_milestone_event(EventType.USER_CORRECTION, triggers=frozenset({EventType.USER_CORRECTION})) is True


def test_all_trigger_reasons_exist():
    assert {t.value for t in ConsolidationTrigger} == {
        "topic_threshold",
        "memory_count",
        "milestone",
        "session_complete",
        "stale_page",
        "manual",
    }
