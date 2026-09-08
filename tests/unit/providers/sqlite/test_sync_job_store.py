from datetime import datetime, timedelta, timezone

import pytest

from domain.enums.sync_job_kind import SyncJobKind
from domain.enums.sync_job_status import SyncJobStatus
from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from domain.models.sync_job import SyncJob
from providers.sqlite.client import SqliteClient
from providers.sqlite.knowledge_store import SqliteKnowledgeStore
from providers.sqlite.sync_job_store import SqliteSyncJobStore


def _store(tmp_path):
    client = SqliteClient(str(tmp_path / "test.db"))
    return client, SqliteSyncJobStore(client)


def test_enqueue_get_round_trip(tmp_path):
    _, store = _store(tmp_path)
    scope = MemoryScope.of(tenant_id="t1")
    job = store.enqueue(SyncJob(kind=SyncJobKind.GRAPH_SYNC, payload={"memory_id": "m1"}, scope=scope, trace_id="tr"))

    fetched = store.get(job.job_id)

    assert fetched.kind == SyncJobKind.GRAPH_SYNC
    assert dict(fetched.payload) == {"memory_id": "m1"}
    assert fetched.scope == scope
    assert fetched.trace_id == "tr"
    assert fetched.status == SyncJobStatus.PENDING


def test_claim_due_returns_only_due_pending_jobs_and_marks_them_running(tmp_path):
    _, store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    due = store.enqueue(SyncJob(next_attempt_at=now - timedelta(seconds=1)))
    store.enqueue(SyncJob(next_attempt_at=now + timedelta(minutes=5)))
    store.enqueue(SyncJob(status=SyncJobStatus.DONE))

    claimed = store.claim_due(now)

    assert [j.job_id for j in claimed] == [due.job_id]
    assert claimed[0].status == SyncJobStatus.RUNNING
    assert store.get(due.job_id).status == SyncJobStatus.RUNNING
    assert store.claim_due(now) == []  # not claimable twice


def test_counts_and_list_by_status(tmp_path):
    _, store = _store(tmp_path)
    store.enqueue(SyncJob())
    store.enqueue(SyncJob(status=SyncJobStatus.DEAD, last_error="x"))

    assert store.counts() == {"pending": 1, "running": 0, "done": 0, "dead": 1}
    assert len(store.list_jobs(status=SyncJobStatus.DEAD)) == 1
    assert len(store.list_jobs()) == 2


def test_recover_running_resets_only_stale_jobs(tmp_path):
    _, store = _store(tmp_path)
    now = datetime.now(timezone.utc)
    stale = store.enqueue(SyncJob(status=SyncJobStatus.RUNNING, updated_at=now - timedelta(hours=1)))
    fresh = store.enqueue(SyncJob(status=SyncJobStatus.RUNNING, updated_at=now))

    assert store.recover_running(older_than=now - timedelta(minutes=10)) == 1
    assert store.get(stale.job_id).status == SyncJobStatus.PENDING
    assert store.get(fresh.job_id).status == SyncJobStatus.RUNNING


def test_survives_reopening_the_database_file(tmp_path):
    path = str(tmp_path / "durable.db")
    SqliteSyncJobStore(SqliteClient(path)).enqueue(SyncJob(payload={"memory_id": "m1"}))

    reopened = SqliteSyncJobStore(SqliteClient(path))

    assert reopened.counts()["pending"] == 1


def test_memory_and_job_commit_atomically_inside_a_transaction(tmp_path):
    client, jobs = _store(tmp_path)
    memories = SqliteKnowledgeStore(client)
    memory = Memory(scope=MemoryScope.of(tenant_id="t1"), content="Team uses PostgreSQL")

    with pytest.raises(RuntimeError):
        with client.transaction():
            memories.save(memory)
            jobs.enqueue(SyncJob(payload={"memory_id": memory.memory_id}))
            raise RuntimeError("crash before commit")

    assert memories.get(memory.memory_id) is None
    assert jobs.counts()["pending"] == 0

    with client.transaction():
        memories.save(memory)
        jobs.enqueue(SyncJob(payload={"memory_id": memory.memory_id}))

    assert memories.get(memory.memory_id) is not None
    assert jobs.counts()["pending"] == 1


def test_transaction_is_reentrant(tmp_path):
    client, jobs = _store(tmp_path)
    with client.transaction():
        with client.transaction():
            jobs.enqueue(SyncJob())
        jobs.enqueue(SyncJob())
    assert jobs.counts()["pending"] == 2


def test_backup_produces_a_readable_copy(tmp_path):
    client, jobs = _store(tmp_path)
    jobs.enqueue(SyncJob())

    copy_path = client.backup(str(tmp_path / "backups" / "copy.db"))

    assert SqliteSyncJobStore(SqliteClient(copy_path)).counts()["pending"] == 1
    assert client.integrity_check() is True
