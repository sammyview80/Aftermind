from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from domain.enums.memory_status import MemoryStatus
from domain.models.memory_lifecycle import MemoryLifecycle

DEFAULT_IMPORTANCE_STEP = 0.05

_TERMINAL_STATUSES = frozenset({MemoryStatus.ARCHIVED, MemoryStatus.EXPIRED, MemoryStatus.FORGOTTEN})


def reinforce(
    lifecycle: MemoryLifecycle, at: Optional[datetime] = None, step: float = DEFAULT_IMPORTANCE_STEP
) -> MemoryLifecycle:
    """Record an access: strengthen importance, reset decay, bump the
    access count. A memory used often should climb back to ACTIVE even
    if it had decayed — but accessing an archived/expired/forgotten
    memory (e.g. during an audit or history lookup) doesn't silently
    resurrect it; that needs an explicit lifecycle action.
    """
    if lifecycle.status in _TERMINAL_STATUSES:
        return lifecycle

    now = at or datetime.now(timezone.utc)
    return replace(
        lifecycle,
        access_count=lifecycle.access_count + 1,
        last_accessed_at=now,
        importance=min(1.0, lifecycle.importance + step),
        decay_score=0.0,
        status=MemoryStatus.ACTIVE,
        updated_at=now,
    )
