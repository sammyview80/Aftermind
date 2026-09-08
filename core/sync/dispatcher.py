"""Failure isolation between the canonical store and secondary stores.

SQLite is authoritative. Neo4j (graph) and OpenKnowledge (documents)
are derived views that must eventually agree with it but must never
be able to fail a memory write. The dispatcher is the one place that
rule is enforced, in two steps that straddle the SQLite transaction:

    enqueue(kind, payload)       # inside the transaction, with the memory
    ... commit ...
    flush(jobs)                  # after commit
      eager mode      -> run each handler now
                         success -> job done,   trace field = ok
                         failure -> job pending (backoff), trace field = pending
      background mode -> leave for the SyncWorker, trace field = pending

Without a SyncJobStore wired (bare in-process use, unit tests), there
is no durability but the isolation still holds: flush() runs the
handler inline and a failure is recorded on the trace instead of raised.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

from core.observability import trace
from core.sync.retry import mark_failed, mark_succeeded
from domain.enums.sync_job_kind import SyncJobKind
from domain.enums.sync_job_status import SyncJobStatus
from domain.interfaces.sync_job_store import SyncJobStore
from domain.models.scope import MemoryScope
from domain.models.sync_job import DEFAULT_MAX_ATTEMPTS, SyncJob

_LOG = logging.getLogger("aftermind.sync")

Handler = Callable[[SyncJob], Any]

EAGER = "eager"
BACKGROUND = "background"

# Which trace field each job kind reports under, so a trace reads
# neo4j_sync=ok / openknowledge_sync=pending rather than job kinds.
TRACE_FIELD_FOR_KIND = {
    SyncJobKind.GRAPH_SYNC: "neo4j_sync",
    SyncJobKind.GRAPH_MARK_STALE: "neo4j_sync",
    SyncJobKind.KNOWLEDGE_CONSOLIDATE: "openknowledge_sync",
    SyncJobKind.KNOWLEDGE_RECONSOLIDATE: "openknowledge_sync",
}

_STATUS_RANK = {trace.SKIPPED: 0, trace.OK: 1, trace.PENDING: 2, trace.FAILED: 3}


class SyncDispatcher:
    def __init__(
        self,
        handlers: Mapping[SyncJobKind, Handler],
        job_store: Optional[SyncJobStore] = None,
        mode: str = EAGER,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        if mode not in (EAGER, BACKGROUND):
            raise ValueError(f"sync mode must be {EAGER!r} or {BACKGROUND!r}, got {mode!r}")
        self._handlers = dict(handlers)
        self._job_store = job_store
        self.mode = mode
        self._max_attempts = max_attempts

    @property
    def durable(self) -> bool:
        return self._job_store is not None

    def enqueue(self, kind: SyncJobKind, payload: dict[str, Any], scope: Optional[MemoryScope] = None) -> SyncJob:
        """Record the sync intent. With a job store this is a durable row
        meant to be written in the caller's open transaction; in eager
        mode the row is born RUNNING so a concurrently polling worker
        doesn't also claim it (crash recovery resets orphaned RUNNING
        rows). Without a job store the job is only an in-memory ticket
        for flush()."""
        active = trace.Tracer.current()
        job = SyncJob(
            kind=kind,
            payload=payload,
            scope=scope,
            trace_id=active.trace_id if active else None,
            max_attempts=self._max_attempts,
            status=SyncJobStatus.RUNNING if (self._job_store is not None and self.mode == EAGER) else SyncJobStatus.PENDING,
        )
        if self._job_store is not None:
            self._job_store.enqueue(job)
            trace.append("sync_jobs", job.job_id)
        return job

    def flush(self, jobs: list[SyncJob]) -> dict[str, str]:
        """Run (or defer) every enqueued job, after the caller's
        transaction committed. Returns {trace_field: status}. Never
        raises for a handler failure — that is the whole point."""
        outcome: dict[str, str] = {}
        for job in jobs:
            field = TRACE_FIELD_FOR_KIND[job.kind]
            if self._job_store is None:
                status = self._run_inline(job)
            elif self.mode == BACKGROUND:
                status = trace.PENDING
            else:
                status = self.execute(job)
            self._annotate(field, status)
            if _STATUS_RANK.get(status, 0) >= _STATUS_RANK.get(outcome.get(field, trace.SKIPPED), 0):
                outcome[field] = status
        return outcome

    def dispatch(self, kind: SyncJobKind, payload: dict[str, Any], scope: Optional[MemoryScope] = None) -> str:
        """enqueue + flush in one step, for callers with no surrounding
        transaction. Returns the resulting status."""
        job = self.enqueue(kind, payload, scope)
        return self.flush([job])[TRACE_FIELD_FOR_KIND[kind]]

    def execute(self, job: SyncJob) -> str:
        """Run one durable job's handler and persist the outcome. Shared
        by the eager path and the background worker so retry semantics
        live in exactly one place. Returns ok / pending (will retry) /
        failed (dead — attempts exhausted)."""
        handler = self._handlers.get(job.kind)
        now = datetime.now(timezone.utc)
        if handler is None:
            self._save(mark_failed(job, f"no handler registered for {job.kind.value}", now=now, force_dead=True))
            return trace.FAILED

        with trace.span(f"sync.{job.kind.value}", reraise=False) as span:
            handler(job)

        if span is None or span.status == trace.OK:
            self._save(mark_succeeded(job, now=now))
            return trace.OK

        updated = mark_failed(job, span.error or "unknown error", now=now)
        self._save(updated)
        _LOG.warning(
            "sync job %s (%s) failed attempt %d/%d: %s",
            job.job_id,
            job.kind.value,
            updated.attempts,
            updated.max_attempts,
            span.error,
        )
        return trace.PENDING if updated.status == SyncJobStatus.PENDING else trace.FAILED

    def _run_inline(self, job: SyncJob) -> str:
        handler = self._handlers.get(job.kind)
        if handler is None:
            return trace.SKIPPED
        with trace.span(f"sync.{job.kind.value}", reraise=False) as span:
            handler(job)
        if span is None or span.status == trace.OK:
            return trace.OK
        _LOG.warning("inline sync %s failed (no job store, not retried): %s", job.kind.value, span.error)
        return trace.FAILED

    def _save(self, job: SyncJob) -> None:
        if self._job_store is not None:
            self._job_store.save(job)

    @staticmethod
    def _annotate(field: str, status: str) -> None:
        """A field aggregates several jobs (graph sync + graph mark-stale
        both report as neo4j_sync); the worst status wins so a trace
        never reads ok when one of its jobs is pending."""
        active = trace.Tracer.current()
        if active is None:
            return
        previous = active.fields.get(field)
        if previous is None or _STATUS_RANK.get(status, 0) >= _STATUS_RANK.get(previous, 0):
            active.record(**{field: status})
