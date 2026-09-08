from datetime import datetime
from typing import Optional, Protocol

from domain.enums.sync_job_status import SyncJobStatus
from domain.models.sync_job import SyncJob


class SyncJobStore(Protocol):
    """Persistence for the transactional outbox (SyncJob). The SQLite
    implementation shares the memory store's database and connection, so
    enqueue() inside a UnitOfWork transaction commits atomically with the
    memory write it describes."""

    def enqueue(self, job: SyncJob) -> SyncJob: ...

    def get(self, job_id: str) -> Optional[SyncJob]: ...

    def save(self, job: SyncJob) -> SyncJob:
        """Persist a status/attempt change to an existing job."""
        ...

    def claim_due(self, now: datetime, limit: int = 10) -> list[SyncJob]:
        """Atomically move up to `limit` PENDING jobs whose next_attempt_at
        <= now into RUNNING and return them — two workers claiming
        concurrently must never receive the same job."""
        ...

    def list_jobs(self, status: Optional[SyncJobStatus] = None, limit: int = 100) -> list[SyncJob]: ...

    def counts(self) -> dict[str, int]:
        """Job count per status value, e.g. {"pending": 3, "dead": 1}."""
        ...

    def recover_running(self, older_than: datetime) -> int:
        """Crash recovery: jobs left RUNNING before `older_than` belong to
        a worker that died mid-flight. Reset them to PENDING and return
        how many were reset."""
        ...
