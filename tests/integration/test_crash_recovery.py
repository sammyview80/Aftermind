"""Crash test for the durable outbox, against a real SQLite file:

    write memory (Neo4j down)  ->  "kill" Aftermind  ->  restart
        -> memory still exists
        -> pending graph sync resumes and completes

"Kill" here is dropping every in-process object and reopening the same
database file with fresh stores — the only state that survives is what
SQLite has on disk, exactly as with a real process crash.
"""
import json
from datetime import datetime, timedelta, timezone

from core.facade import AftermindService
from core.observability import trace
from core.sync.worker import SyncWorker
from domain.enums.event_type import EventType
from domain.enums.sync_job_kind import SyncJobKind
from domain.enums.sync_job_status import SyncJobStatus
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope
from providers.inmemory.store import InMemoryGraphStore
from providers.sqlite.checkpoint_store import SqliteCheckpointStore
from providers.sqlite.client import SqliteClient
from providers.sqlite.decision_store import SqliteDecisionStore
from providers.sqlite.episode_store import SqliteEpisodeStore
from providers.sqlite.knowledge_store import SqliteKnowledgeStore
from providers.sqlite.lifecycle_store import SqliteLifecycleStore
from providers.sqlite.sync_job_store import SqliteSyncJobStore


class ScriptedLLM:
    def complete(self, prompt: str) -> str:
        if "EXISTING MEMORIES:" in prompt:
            return json.dumps({"action": "create", "target_memory_id": None, "confidence": 0.9, "reasoning": "x"})
        return "[]"


class DownGraphStore(InMemoryGraphStore):
    def upsert_entity(self, name, scope=None):
        raise ConnectionError("neo4j: connection refused")

    def upsert_relationship(self, source, relation, target, scope=None):
        raise ConnectionError("neo4j: connection refused")


def _boot(db_path: str, graph_store, sync_mode: str = "eager"):
    """One 'process start': fresh client + stores over the same file."""
    client = SqliteClient(db_path)
    service = AftermindService(
        knowledge_store=SqliteKnowledgeStore(client),
        graph_store=graph_store,
        checkpoint_store=SqliteCheckpointStore(client),
        lifecycle_store=SqliteLifecycleStore(client),
        llm_provider=ScriptedLLM(),
        episode_store=SqliteEpisodeStore(client),
        decision_store=SqliteDecisionStore(client),
        sync_job_store=SqliteSyncJobStore(client),
        unit_of_work=client,
        sync_mode=sync_mode,
        tracer=trace.Tracer(sinks=[]),
    )
    worker = SyncWorker(SqliteSyncJobStore(client), service.sync, tracer=trace.Tracer(sinks=[]))
    return client, service, worker


def _experience(text, scope):
    return Experience(scope=scope, events=[Event(event_type=EventType.AGENT_MESSAGE)], output=text)


def test_memory_survives_crash_and_pending_graph_sync_resumes_on_restart(tmp_path):
    db_path = str(tmp_path / "aftermind.db")
    scope = MemoryScope.of(tenant_id="hermes", project_id="aftermind")

    # --- process 1: Neo4j is down while a memory is written -------------
    _, service, _ = _boot(db_path, DownGraphStore())
    memory = service.observe(_experience("Aftermind uses PostgreSQL", scope))
    assert memory is not None

    jobs_before = SqliteSyncJobStore(SqliteClient(db_path))
    assert jobs_before.counts()[SyncJobStatus.PENDING.value] == 1
    del service  # "kill -9"

    # --- process 2: restart with Neo4j reachable -------------------------
    graph = InMemoryGraphStore()
    _, service2, worker2 = _boot(db_path, graph)

    assert service2.knowledge_store.get(memory.memory_id).content == "Aftermind uses PostgreSQL"
    assert graph.find_related("Aftermind", scope=scope) == []  # not yet synced

    worker2.recover()
    # The job is backed off ~1s from the failed eager attempt; run as if later.
    result = worker2.run_once(now=datetime.now(timezone.utc) + timedelta(minutes=1))

    assert result == {"ok": 1, "pending": 0, "failed": 0}
    assert graph.find_related("Aftermind", scope=scope) == ["PostgreSQL"]
    job = SqliteSyncJobStore(SqliteClient(db_path)).list_jobs()[0]
    assert job.status == SyncJobStatus.DONE
    assert job.kind == SyncJobKind.GRAPH_SYNC
    assert job.attempts == 2  # one failed eager attempt + one successful retry

    # And recall in the new process sees the memory from SQLite regardless.
    recalled = service2.recall(RecallQuery(scope=scope, text="What database does Aftermind use?"))
    assert "PostgreSQL" in recalled.context


def test_crash_mid_eager_sync_leaves_a_running_job_that_recovery_requeues(tmp_path):
    db_path = str(tmp_path / "aftermind.db")
    scope = MemoryScope.of(tenant_id="hermes", project_id="aftermind")
    _, service, _ = _boot(db_path, InMemoryGraphStore())

    # Simulate dying after the SQLite commit but before the eager flush
    # finished: enqueue (RUNNING row) without ever executing it.
    memory = service.knowledge_store.save(
        __import__("domain.models.memory", fromlist=["Memory"]).Memory(scope=scope, content="Aftermind uses SQLite")
    )
    service.sync.enqueue(SyncJobKind.GRAPH_SYNC, {"memory_id": memory.memory_id}, scope)
    store = SqliteSyncJobStore(SqliteClient(db_path))
    assert store.counts()[SyncJobStatus.RUNNING.value] == 1
    del service

    graph = InMemoryGraphStore()
    _, service2, worker2 = _boot(db_path, graph)
    worker2.stale_running_seconds = 0

    assert worker2.recover(now=datetime.now(timezone.utc) + timedelta(seconds=1)) == 1
    assert worker2.drain() == {"ok": 1, "pending": 0, "failed": 0}
    assert graph.find_related("Aftermind", scope=scope) == ["SQLite"]


def test_background_mode_backlog_is_drained_after_restart(tmp_path):
    db_path = str(tmp_path / "aftermind.db")
    scope = MemoryScope.of(tenant_id="hermes", project_id="aftermind")
    _, service, _ = _boot(db_path, InMemoryGraphStore(), sync_mode="background")
    for text in ("Aftermind uses PostgreSQL", "Graphiti runs on Neo4j"):
        assert service.observe(_experience(text, scope)) is not None
    assert SqliteSyncJobStore(SqliteClient(db_path)).counts()[SyncJobStatus.PENDING.value] == 2
    del service

    graph = InMemoryGraphStore()
    _, _, worker2 = _boot(db_path, graph, sync_mode="background")
    assert worker2.drain() == {"ok": 2, "pending": 0, "failed": 0}
    assert graph.find_related("Aftermind", scope=scope) == ["PostgreSQL"]
    assert graph.find_related("Graphiti", scope=scope) == ["Neo4j"]
