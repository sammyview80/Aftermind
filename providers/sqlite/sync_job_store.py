from datetime import datetime
from typing import Optional

from domain.enums.sync_job_kind import SyncJobKind
from domain.enums.sync_job_status import SyncJobStatus
from domain.models.sync_job import SyncJob
from providers.sqlite.client import SqliteClient
from providers.sqlite.serialize import (
    dump_json,
    dump_scope_levels,
    load_dt_required,
    load_json,
    load_scope,
    scope_key,
)


def _row_to_job(row) -> SyncJob:
    return SyncJob(
        job_id=row["job_id"],
        kind=SyncJobKind(row["kind"]),
        payload=load_json(row["payload"]),
        scope=load_scope(row["scope_levels"]),
        status=SyncJobStatus(row["status"]),
        attempts=row["attempts"],
        max_attempts=row["max_attempts"],
        next_attempt_at=load_dt_required(row["next_attempt_at"]),
        last_error=row["last_error"],
        trace_id=row["trace_id"],
        created_at=load_dt_required(row["created_at"]),
        updated_at=load_dt_required(row["updated_at"]),
    )


class SqliteSyncJobStore:
    """SyncJobStore in the same SQLite file as the memories — the point
    of a transactional outbox is that enqueue() commits with the memory
    write, which only works when both live in one database."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def enqueue(self, job: SyncJob) -> SyncJob:
        return self.save(job)

    def save(self, job: SyncJob) -> SyncJob:
        with self._client.connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_jobs (
                    job_id, kind, payload, scope_key, scope_levels, status, attempts, max_attempts,
                    next_attempt_at, last_error, trace_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    status=excluded.status, attempts=excluded.attempts,
                    next_attempt_at=excluded.next_attempt_at, last_error=excluded.last_error,
                    updated_at=excluded.updated_at
                """,
                (
                    job.job_id,
                    job.kind.value,
                    dump_json(dict(job.payload)),
                    scope_key(job.scope),
                    dump_scope_levels(job.scope),
                    job.status.value,
                    job.attempts,
                    job.max_attempts,
                    job.next_attempt_at.isoformat(),
                    job.last_error,
                    job.trace_id,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat(),
                ),
            )
        return job

    def get(self, job_id: str) -> Optional[SyncJob]:
        with self._client.connect() as conn:
            row = conn.execute("SELECT * FROM sync_jobs WHERE job_id = ?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def claim_due(self, now: datetime, limit: int = 10) -> list[SyncJob]:
        # UPDATE ... RETURNING inside the connection's own transaction:
        # two workers racing here serialize on SQLite's write lock, so a
        # job is handed to exactly one of them.
        with self._client.connect() as conn:
            rows = conn.execute(
                """
                UPDATE sync_jobs
                SET status = ?, updated_at = ?
                WHERE job_id IN (
                    SELECT job_id FROM sync_jobs
                    WHERE status = ? AND next_attempt_at <= ?
                    ORDER BY next_attempt_at, created_at
                    LIMIT ?
                )
                RETURNING *
                """,
                (SyncJobStatus.RUNNING.value, now.isoformat(), SyncJobStatus.PENDING.value, now.isoformat(), limit),
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def list_jobs(self, status: Optional[SyncJobStatus] = None, limit: int = 100) -> list[SyncJob]:
        with self._client.connect() as conn:
            if status is None:
                rows = conn.execute("SELECT * FROM sync_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM sync_jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status.value, limit)
                ).fetchall()
        return [_row_to_job(row) for row in rows]

    def counts(self) -> dict[str, int]:
        with self._client.connect() as conn:
            rows = conn.execute("SELECT status, COUNT(*) AS n FROM sync_jobs GROUP BY status").fetchall()
        counts = {status.value: 0 for status in SyncJobStatus}
        for row in rows:
            counts[row["status"]] = row["n"]
        return counts

    def recover_running(self, older_than: datetime) -> int:
        with self._client.connect() as conn:
            cursor = conn.execute(
                "UPDATE sync_jobs SET status = ?, updated_at = ? WHERE status = ? AND updated_at <= ?",
                (
                    SyncJobStatus.PENDING.value,
                    older_than.isoformat(),
                    SyncJobStatus.RUNNING.value,
                    older_than.isoformat(),
                ),
            )
            return cursor.rowcount
