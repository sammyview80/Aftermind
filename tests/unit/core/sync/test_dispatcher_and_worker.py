from datetime import datetime, timedelta, timezone

import pytest

from core.observability import trace
from core.sync.dispatcher import BACKGROUND, EAGER, SyncDispatcher
from core.sync.worker import SyncWorker
from domain.enums.sync_job_kind import SyncJobKind
from domain.enums.sync_job_status import SyncJobStatus
from providers.inmemory.store import InMemorySyncJobStore


class FlakyHandler:
    """Fails `failures` times, then succeeds — a store that comes back."""

    def __init__(self, failures: int = 0) -> None:
        self.failures = failures
        self.calls: list = []

    def __call__(self, job):
        self.calls.append(dict(job.payload))
        if self.failures > 0:
            self.failures -= 1
            raise ConnectionError("neo4j unreachable")


def _tracer():
    sink = trace.InMemoryTraceSink()
    return trace.Tracer(sinks=[sink]), sink


def test_eager_success_marks_job_done_and_trace_ok():
    store = InMemorySyncJobStore()
    handler = FlakyHandler()
    dispatcher = SyncDispatcher({SyncJobKind.GRAPH_SYNC: handler}, job_store=store, mode=EAGER)
    tracer, sink = _tracer()

    with tracer.begin("observe"):
        status = dispatcher.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": "m1"})

    assert status == trace.OK
    assert handler.calls == [{"memory_id": "m1"}]
    assert store.counts()[SyncJobStatus.DONE.value] == 1
    assert sink.recent()[0].fields["neo4j_sync"] == "ok"
    assert sink.recent()[0].fields["sync_jobs"]  # job id recorded for correlation


def test_eager_failure_leaves_a_pending_job_and_does_not_raise():
    store = InMemorySyncJobStore()
    handler = FlakyHandler(failures=1)
    dispatcher = SyncDispatcher({SyncJobKind.GRAPH_SYNC: handler}, job_store=store, mode=EAGER)
    tracer, sink = _tracer()

    with tracer.begin("observe"):
        status = dispatcher.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": "m1"})

    assert status == trace.PENDING
    job = store.list_jobs()[0]
    assert job.status == SyncJobStatus.PENDING
    assert job.attempts == 1
    assert "ConnectionError" in job.last_error
    assert job.next_attempt_at > datetime.now(timezone.utc)  # backed off
    assert sink.recent()[0].fields["neo4j_sync"] == "pending"
    assert sink.recent()[0].status == trace.OK  # the observe itself is fine


def test_eager_enqueue_is_born_running_so_a_polling_worker_cannot_double_execute():
    store = InMemorySyncJobStore()
    dispatcher = SyncDispatcher({SyncJobKind.GRAPH_SYNC: FlakyHandler()}, job_store=store, mode=EAGER)

    job = dispatcher.enqueue(SyncJobKind.GRAPH_SYNC, {"memory_id": "m1"})

    assert store.get(job.job_id).status == SyncJobStatus.RUNNING
    assert store.claim_due(datetime.now(timezone.utc)) == []


def test_background_mode_only_enqueues():
    store = InMemorySyncJobStore()
    handler = FlakyHandler()
    dispatcher = SyncDispatcher({SyncJobKind.GRAPH_SYNC: handler}, job_store=store, mode=BACKGROUND)

    status = dispatcher.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": "m1"})

    assert status == trace.PENDING
    assert handler.calls == []
    assert store.counts()[SyncJobStatus.PENDING.value] == 1


def test_without_a_job_store_failures_are_isolated_but_not_retried():
    handler = FlakyHandler(failures=1)
    dispatcher = SyncDispatcher({SyncJobKind.GRAPH_SYNC: handler}, job_store=None)
    tracer, sink = _tracer()

    with tracer.begin("observe"):
        status = dispatcher.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": "m1"})

    assert status == trace.FAILED
    assert not dispatcher.durable
    assert sink.recent()[0].fields["neo4j_sync"] == "failed"


def test_worst_status_wins_when_several_jobs_share_a_trace_field():
    store = InMemorySyncJobStore()
    dispatcher = SyncDispatcher(
        {SyncJobKind.GRAPH_SYNC: FlakyHandler(), SyncJobKind.GRAPH_MARK_STALE: FlakyHandler(failures=1)},
        job_store=store,
    )
    tracer, sink = _tracer()
    with tracer.begin("observe"):
        dispatcher.dispatch(SyncJobKind.GRAPH_MARK_STALE, {"memory_id": "old"})
        dispatcher.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": "new"})
    assert sink.recent()[0].fields["neo4j_sync"] == "pending"


def test_missing_handler_is_dead_immediately():
    store = InMemorySyncJobStore()
    dispatcher = SyncDispatcher({}, job_store=store)
    assert dispatcher.dispatch(SyncJobKind.GRAPH_SYNC, {}) == trace.FAILED
    assert store.list_jobs()[0].status == SyncJobStatus.DEAD


def test_invalid_mode_is_rejected():
    with pytest.raises(ValueError):
        SyncDispatcher({}, mode="sometimes")


def test_worker_retries_pending_job_until_the_store_comes_back():
    store = InMemorySyncJobStore()
    handler = FlakyHandler(failures=2)
    dispatcher = SyncDispatcher({SyncJobKind.GRAPH_SYNC: handler}, job_store=store, mode=BACKGROUND)
    tracer, sink = _tracer()
    worker = SyncWorker(store, dispatcher, tracer=tracer)

    dispatcher.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": "m1"})
    job_id = store.list_jobs()[0].job_id

    now = datetime.now(timezone.utc)
    assert worker.run_once(now=now) == {"ok": 0, "pending": 1, "failed": 0}
    assert worker.run_once(now=now) == {"ok": 0, "pending": 0, "failed": 0}  # backed off, not due yet
    assert worker.run_once(now=now + timedelta(seconds=2)) == {"ok": 0, "pending": 1, "failed": 0}
    assert worker.run_once(now=now + timedelta(seconds=10)) == {"ok": 1, "pending": 0, "failed": 0}

    assert store.get(job_id).status == SyncJobStatus.DONE
    assert store.get(job_id).attempts == 3
    # Each attempt is its own child trace linked to the originating job.
    child_traces = [t for t in sink.recent() if t.operation == "sync_job"]
    assert len(child_traces) == 3
    assert {t.fields["result"] for t in child_traces} == {"pending", "ok"}


def test_worker_marks_job_dead_after_max_attempts_and_retry_dead_requeues_it():
    store = InMemorySyncJobStore()
    handler = FlakyHandler(failures=100)
    dispatcher = SyncDispatcher({SyncJobKind.GRAPH_SYNC: handler}, job_store=store, mode=BACKGROUND, max_attempts=2)
    worker = SyncWorker(store, dispatcher, tracer=trace.Tracer(sinks=[]))
    dispatcher.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": "m1"})

    far_future = datetime.now(timezone.utc) + timedelta(hours=1)
    worker.run_once(now=far_future)
    assert worker.run_once(now=far_future + timedelta(hours=1)) == {"ok": 0, "pending": 0, "failed": 1}
    assert store.counts()[SyncJobStatus.DEAD.value] == 1

    assert worker.retry_dead() == 1
    assert store.counts()[SyncJobStatus.PENDING.value] == 1


def test_worker_recover_resets_orphaned_running_jobs():
    store = InMemorySyncJobStore()
    dispatcher = SyncDispatcher({SyncJobKind.GRAPH_SYNC: FlakyHandler()}, job_store=store, mode=EAGER)
    # Eager enqueue = RUNNING; simulate the process dying before flush().
    dispatcher.enqueue(SyncJobKind.GRAPH_SYNC, {"memory_id": "m1"})
    worker = SyncWorker(store, dispatcher, tracer=trace.Tracer(sinks=[]), stale_running_seconds=0)

    assert worker.recover(now=datetime.now(timezone.utc) + timedelta(seconds=1)) == 1
    assert store.list_jobs()[0].status == SyncJobStatus.PENDING
    assert worker.drain() == {"ok": 1, "pending": 0, "failed": 0}


def test_worker_thread_starts_and_stops():
    store = InMemorySyncJobStore()
    dispatcher = SyncDispatcher({SyncJobKind.GRAPH_SYNC: FlakyHandler()}, job_store=store, mode=BACKGROUND)
    worker = SyncWorker(store, dispatcher, tracer=trace.Tracer(sinks=[]), poll_interval=0.01)
    dispatcher.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": "m1"})

    worker.start()
    deadline = datetime.now(timezone.utc) + timedelta(seconds=2)
    while store.counts()[SyncJobStatus.DONE.value] == 0 and datetime.now(timezone.utc) < deadline:
        pass
    worker.stop()

    assert not worker.running
    assert store.counts()[SyncJobStatus.DONE.value] == 1
