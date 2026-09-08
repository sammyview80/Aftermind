from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional

from domain.enums.memory_status import MemoryStatus
from domain.models.memory_lifecycle import MemoryLifecycle

DEFAULT_ARCHIVE_REASON = "superseded"


def archive(
    lifecycle: MemoryLifecycle, reason: str = DEFAULT_ARCHIVE_REASON, at: Optional[datetime] = None
) -> MemoryLifecycle:
    """Move a memory out of active recall without deleting it — for a
    memory that's been superseded by a newer fact, or manually archived.
    Distinct from forgetting: an archived memory's content and
    provenance links stay intact, it's just no longer surfaced."""
    now = at or datetime.now(timezone.utc)
    return replace(
        lifecycle,
        status=MemoryStatus.ARCHIVED,
        metadata={**lifecycle.metadata, "archived_reason": reason, "archived_at": now.isoformat()},
        updated_at=now,
    )
