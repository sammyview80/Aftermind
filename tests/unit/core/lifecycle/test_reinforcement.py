from datetime import datetime, timezone

from core.lifecycle.reinforcement import reinforce
from domain.enums.memory_status import MemoryStatus
from domain.models.memory_lifecycle import MemoryLifecycle


def test_reinforce_increments_access_count_and_sets_last_accessed():
    lifecycle = MemoryLifecycle(memory_id="m1")
    now = datetime.now(timezone.utc)

    reinforced = reinforce(lifecycle, at=now)

    assert reinforced.access_count == 1
    assert reinforced.last_accessed_at == now


def test_reinforce_increases_importance_and_resets_decay():
    lifecycle = MemoryLifecycle(memory_id="m1", importance=0.5, decay_score=0.6)
    reinforced = reinforce(lifecycle, step=0.1)
    assert reinforced.importance == 0.6
    assert reinforced.decay_score == 0.0


def test_reinforce_caps_importance_at_one():
    lifecycle = MemoryLifecycle(memory_id="m1", importance=0.98)
    assert reinforce(lifecycle, step=0.1).importance == 1.0


def test_reinforce_revives_decayed_status_to_active():
    lifecycle = MemoryLifecycle(memory_id="m1", status=MemoryStatus.DECAYED)
    assert reinforce(lifecycle).status == MemoryStatus.ACTIVE


def test_reinforce_does_not_revive_terminal_statuses():
    for status in (MemoryStatus.ARCHIVED, MemoryStatus.EXPIRED, MemoryStatus.FORGOTTEN):
        lifecycle = MemoryLifecycle(memory_id="m1", status=status, access_count=5)
        result = reinforce(lifecycle)
        assert result.status == status
        assert result.access_count == 5  # unchanged — no-op
