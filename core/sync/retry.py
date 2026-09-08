from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from domain.enums.sync_job_status import SyncJobStatus
from domain.models.sync_job import SyncJob

BACKOFF_BASE_SECONDS = 1.0
BACKOFF_MAX_SECONDS = 300.0


def backoff_seconds(attempts: int, base: float = BACKOFF_BASE_SECONDS, cap: float = BACKOFF_MAX_SECONDS) -> float:
    """Exponential: 1s, 2s, 4s, ... capped at 5 minutes. `attempts` is
    the number already made (so the first retry waits `base`)."""
    return min(cap, base * (2 ** max(attempts - 1, 0)))


def mark_succeeded(job: SyncJob, now: Optional[datetime] = None) -> SyncJob:
    now = now or datetime.now(timezone.utc)
    return replace(job, status=SyncJobStatus.DONE, attempts=job.attempts + 1, last_error=None, updated_at=now)


def mark_failed(job: SyncJob, error: str, now: Optional[datetime] = None, force_dead: bool = False) -> SyncJob:
    """Record a failed attempt: schedule the next one with backoff, or
    mark DEAD once max_attempts is reached (or `force_dead`, for errors
    a retry can't fix such as a missing handler)."""
    now = now or datetime.now(timezone.utc)
    attempts = job.attempts + 1
    if force_dead or attempts >= job.max_attempts:
        return replace(job, status=SyncJobStatus.DEAD, attempts=attempts, last_error=error[:2000], updated_at=now)
    return replace(
        job,
        status=SyncJobStatus.PENDING,
        attempts=attempts,
        last_error=error[:2000],
        next_attempt_at=now + timedelta(seconds=backoff_seconds(attempts)),
        updated_at=now,
    )


def requeue(job: SyncJob, now: Optional[datetime] = None) -> SyncJob:
    """Manual retry of a DEAD job: back to PENDING, due immediately,
    attempt counter reset so it gets a full run of retries again."""
    now = now or datetime.now(timezone.utc)
    return replace(job, status=SyncJobStatus.PENDING, attempts=0, next_attempt_at=now, updated_at=now)
