from datetime import datetime, timedelta, timezone

from core.sync.retry import backoff_seconds, mark_failed, mark_succeeded, requeue
from domain.enums.sync_job_status import SyncJobStatus
from domain.models.sync_job import SyncJob


def test_backoff_is_exponential_and_capped():
    assert backoff_seconds(1) == 1.0
    assert backoff_seconds(2) == 2.0
    assert backoff_seconds(3) == 4.0
    assert backoff_seconds(50) == 300.0


def test_mark_failed_schedules_retry_with_backoff():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = SyncJob(max_attempts=3)

    failed = mark_failed(job, "neo4j down", now=now)

    assert failed.status == SyncJobStatus.PENDING
    assert failed.attempts == 1
    assert failed.last_error == "neo4j down"
    assert failed.next_attempt_at == now + timedelta(seconds=1)


def test_mark_failed_goes_dead_at_max_attempts():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    job = SyncJob(max_attempts=2, attempts=1)

    dead = mark_failed(job, "still down", now=now)

    assert dead.status == SyncJobStatus.DEAD
    assert dead.attempts == 2


def test_mark_failed_force_dead_skips_retries():
    dead = mark_failed(SyncJob(max_attempts=10), "no handler", force_dead=True)
    assert dead.status == SyncJobStatus.DEAD


def test_mark_succeeded_clears_error_and_counts_attempt():
    job = SyncJob(attempts=2, last_error="x")
    done = mark_succeeded(job)
    assert done.status == SyncJobStatus.DONE
    assert done.attempts == 3
    assert done.last_error is None


def test_requeue_resets_a_dead_job():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    dead = SyncJob(status=SyncJobStatus.DEAD, attempts=10)
    again = requeue(dead, now=now)
    assert again.status == SyncJobStatus.PENDING
    assert again.attempts == 0
    assert again.next_attempt_at == now
