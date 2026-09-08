from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.enums.sync_job_kind import SyncJobKind
from domain.enums.sync_job_status import SyncJobStatus
from domain.models.scope import MemoryScope

DEFAULT_MAX_ATTEMPTS = 10


@dataclass(frozen=True)
class SyncJob:
    """One unit of the transactional outbox: "propagate this memory
    change to a secondary store". Written in the same SQLite transaction
    as the memory itself, so a memory can never exist without its sync
    intent (or vice versa), and a crash between "SQLite committed" and
    "Neo4j/OpenKnowledge updated" leaves a durable, retryable record
    rather than a silent gap.

    `payload` is deliberately minimal (memory_id plus a flag or two);
    the handler reloads the memory from the canonical store, so a job
    retried hours later acts on current data, not a stale snapshot.
    """

    job_id: str = field(default_factory=lambda: str(uuid4()))
    kind: SyncJobKind = SyncJobKind.GRAPH_SYNC
    payload: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    scope: Optional[MemoryScope] = None
    status: SyncJobStatus = SyncJobStatus.PENDING
    attempts: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    next_attempt_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_error: Optional[str] = None
    trace_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
