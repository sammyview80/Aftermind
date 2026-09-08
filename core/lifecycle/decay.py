from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from domain.enums.memory_status import MemoryStatus
from domain.models.memory_lifecycle import MemoryLifecycle

DEFAULT_HALF_LIFE_DAYS = 180
DEFAULT_DECAY_THRESHOLD = 0.3
DEFAULT_EXPIRE_THRESHOLD = 0.9

_TERMINAL_STATUSES = frozenset({MemoryStatus.ARCHIVED, MemoryStatus.FORGOTTEN})


def compute_decay_score(
    lifecycle: MemoryLifecycle, now: Optional[datetime] = None, half_life_days: float = DEFAULT_HALF_LIFE_DAYS
) -> float:
    """0 (fresh) to 1 (fully stale), growing with time since last use.
    Higher importance stretches the half-life — a memory that's been
    reinforced a lot decays slower than one that's never been touched."""
    now = now or datetime.now(timezone.utc)
    reference = lifecycle.last_accessed_at or lifecycle.created_at
    elapsed_days = max((now - reference).total_seconds() / 86400, 0.0)
    half_life = half_life_days * (1 + lifecycle.importance)
    if half_life <= 0:
        return 1.0
    return min(1.0, 1 - 0.5 ** (elapsed_days / half_life))


def _status_for_score(score: float, decay_threshold: float, expire_threshold: float) -> MemoryStatus:
    if score >= expire_threshold:
        return MemoryStatus.EXPIRED
    if score >= decay_threshold:
        return MemoryStatus.DECAYED
    return MemoryStatus.ACTIVE


def apply_decay(
    lifecycle: MemoryLifecycle,
    now: Optional[datetime] = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    decay_threshold: float = DEFAULT_DECAY_THRESHOLD,
    expire_threshold: float = DEFAULT_EXPIRE_THRESHOLD,
) -> MemoryLifecycle:
    """Recompute decay_score and status from time-since-use. A no-op on
    memories already in a terminal state (archived/forgotten) — decay
    only governs active/decayed/expired transitions."""
    if lifecycle.status in _TERMINAL_STATUSES:
        return lifecycle

    now = now or datetime.now(timezone.utc)
    score = compute_decay_score(lifecycle, now, half_life_days)
    status = _status_for_score(score, decay_threshold, expire_threshold)

    if lifecycle.valid_until is not None and now >= lifecycle.valid_until:
        status = MemoryStatus.EXPIRED

    return replace(lifecycle, decay_score=score, status=status, updated_at=now)
