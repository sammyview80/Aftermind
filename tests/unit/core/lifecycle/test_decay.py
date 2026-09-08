from datetime import datetime, timedelta, timezone

from core.lifecycle.decay import apply_decay, compute_decay_score
from domain.enums.memory_status import MemoryStatus
from domain.models.memory_lifecycle import MemoryLifecycle


def test_freshly_created_memory_has_near_zero_decay():
    now = datetime.now(timezone.utc)
    lifecycle = MemoryLifecycle(memory_id="m1", created_at=now)
    assert compute_decay_score(lifecycle, now=now) == 0.0


def test_decay_grows_with_elapsed_time():
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=90)
    lifecycle = MemoryLifecycle(memory_id="m1", created_at=created, importance=0.5)
    score = compute_decay_score(lifecycle, now=now, half_life_days=180)
    assert 0.0 < score < 1.0


def test_higher_importance_decays_slower():
    now = datetime.now(timezone.utc)
    created = now - timedelta(days=90)
    low = MemoryLifecycle(memory_id="m1", created_at=created, importance=0.1)
    high = MemoryLifecycle(memory_id="m2", created_at=created, importance=0.9)

    assert compute_decay_score(high, now=now) < compute_decay_score(low, now=now)


def test_apply_decay_marks_active_when_score_below_decay_threshold():
    now = datetime.now(timezone.utc)
    lifecycle = MemoryLifecycle(memory_id="m1", created_at=now - timedelta(days=1))
    result = apply_decay(lifecycle, now=now)
    assert result.status == MemoryStatus.ACTIVE


def test_apply_decay_marks_decayed_when_unused_long_enough():
    now = datetime.now(timezone.utc)
    lifecycle = MemoryLifecycle(memory_id="m1", created_at=now - timedelta(days=190), importance=0.0)
    result = apply_decay(lifecycle, now=now, half_life_days=180, decay_threshold=0.3, expire_threshold=0.9)
    assert result.status == MemoryStatus.DECAYED


def test_apply_decay_marks_expired_when_score_crosses_expire_threshold():
    now = datetime.now(timezone.utc)
    lifecycle = MemoryLifecycle(memory_id="m1", created_at=now - timedelta(days=2000), importance=0.0)
    result = apply_decay(lifecycle, now=now, half_life_days=180)
    assert result.status == MemoryStatus.EXPIRED


def test_apply_decay_respects_explicit_valid_until():
    now = datetime.now(timezone.utc)
    lifecycle = MemoryLifecycle(memory_id="m1", created_at=now, valid_until=now - timedelta(seconds=1))
    result = apply_decay(lifecycle, now=now)
    assert result.status == MemoryStatus.EXPIRED


def test_apply_decay_is_noop_on_terminal_statuses():
    for status in (MemoryStatus.ARCHIVED, MemoryStatus.FORGOTTEN):
        lifecycle = MemoryLifecycle(memory_id="m1", status=status, decay_score=0.0)
        result = apply_decay(lifecycle, now=datetime.now(timezone.utc) + timedelta(days=9999))
        assert result.status == status
        assert result.decay_score == 0.0
