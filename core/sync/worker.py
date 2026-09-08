"""Background worker draining the sync outbox.

Runs in a daemon thread next to the API (or as its own process via
`aftermind worker`). Each tick claims due jobs atomically from the
SyncJobStore and executes them through the same SyncDispatcher the
eager path uses, so success/backoff/dead semantics are identical
whether a job ran inline or hours later after Neo4j came back.

On start it performs crash recovery: any job left RUNNING by a worker
that died mid-flight is reset to PENDING.
"""
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from core.observability import trace
from core.sync.dispatcher import SyncDispatcher
from core.sync.retry import requeue
from domain.enums.sync_job_status import SyncJobStatus
from domain.interfaces.sync_job_store import SyncJobStore

_LOG = logging.getLogger("aftermind.sync")

DEFAULT_POLL_INTERVAL_SECONDS = 2.0
DEFAULT_BATCH_SIZE = 10
# A job RUNNING longer than this is assumed orphaned by a dead worker.
DEFAULT_STALE_RUNNING_SECONDS = 600.0


class SyncWorker:
    def __init__(
        self,
        job_store: SyncJobStore,
        dispatcher: SyncDispatcher,
        tracer: trace.Tracer = trace.default_tracer,
        poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
        batch_size: int = DEFAULT_BATCH_SIZE,
        stale_running_seconds: float = DEFAULT_STALE_RUNNING_SECONDS,
    ) -> None:
        self._job_store = job_store
        self._dispatcher = dispatcher
        self._tracer = tracer
        self.poll_interval = poll_interval
        self.batch_size = batch_size
        self.stale_running_seconds = stale_running_seconds
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def recover(self, now: Optional[datetime] = None) -> int:
        """Reset jobs orphaned in RUNNING (worker died) back to PENDING.
        Called on start; safe to call any time."""
        now = now or datetime.now(timezone.utc)
        reset = self._job_store.recover_running(older_than=now - timedelta(seconds=self.stale_running_seconds))
        if reset:
            _LOG.info("sync worker recovered %d orphaned running job(s)", reset)
        return reset

    def run_once(self, now: Optional[datetime] = None) -> dict[str, int]:
        """Claim and execute one batch of due jobs. Returns counts by
        outcome, e.g. {"ok": 2, "pending": 1, "failed": 0}."""
        now = now or datetime.now(timezone.utc)
        outcome = {trace.OK: 0, trace.PENDING: 0, trace.FAILED: 0}
        for job in self._job_store.claim_due(now, limit=self.batch_size):
            scope_key = job.scope.key() if job.scope is not None else None
            with self._tracer.child("sync_job", parent_trace_id=job.trace_id, scope=scope_key) as t:
                t.record(job_id=job.job_id, kind=job.kind.value, attempt=job.attempts + 1, **dict(job.payload))
                status = self._dispatcher.execute(job)
                t.record(result=status)
            outcome[status] = outcome.get(status, 0) + 1
        return outcome

    def drain(self, max_batches: int = 100) -> dict[str, int]:
        """Process every currently-due job (bounded), for tests, the CLI
        and the /maintenance/sync/run endpoint."""
        total: dict[str, int] = {}
        for _ in range(max_batches):
            batch = self.run_once()
            for k, v in batch.items():
                total[k] = total.get(k, 0) + v
            if sum(batch.values()) == 0:
                break
        return total

    def retry_dead(self, job_id: Optional[str] = None) -> int:
        """Requeue DEAD jobs (one by id, or all). Returns how many."""
        if job_id is not None:
            job = self._job_store.get(job_id)
            if job is None or job.status != SyncJobStatus.DEAD:
                return 0
            self._job_store.save(requeue(job))
            return 1
        dead = self._job_store.list_jobs(status=SyncJobStatus.DEAD, limit=10_000)
        for job in dead:
            self._job_store.save(requeue(job))
        return len(dead)

    def run_forever(self) -> None:
        self.recover()
        while not self._stop.is_set():
            try:
                # Jobs orphaned *after* start (a request thread died mid-flush,
                # a hung handler) must be picked up too — recovery is one cheap
                # UPDATE, so run it every tick rather than only at boot.
                self.recover()
                processed = sum(self.run_once().values())
            except Exception:  # noqa: BLE001 - the loop must survive a bad tick
                _LOG.exception("sync worker tick failed")
                processed = 0
            # Drain quickly while there is work; sleep only when idle.
            if processed == 0:
                self._stop.wait(self.poll_interval)

    def start(self) -> "SyncWorker":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self.run_forever, name="aftermind-sync-worker", daemon=True)
        self._thread.start()
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout)
            self._thread = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()
