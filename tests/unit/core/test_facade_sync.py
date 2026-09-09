"""Failure isolation + tracing at the facade boundary: SQLite is
canonical; Neo4j/OpenKnowledge outages leave durable retry jobs and
`pending` trace fields, never a lost memory or a failed observe()."""
import json

from core.facade import AftermindService
from core.observability import trace
from core.sync.dispatcher import BACKGROUND
from core.sync.worker import SyncWorker
from domain.enums.event_type import EventType
from domain.enums.sync_job_kind import SyncJobKind
from domain.enums.sync_job_status import SyncJobStatus
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope
from providers.inmemory.store import (
    InMemoryCheckpointStore,
    InMemoryGraphStore,
    InMemoryKnowledgeStore,
    InMemoryLifecycleStore,
    InMemorySyncJobStore,
)


class ScriptedLLM:
    def __init__(self, action="create", target_memory_id=None, consolidation_response=None):
        self.action = action
        self.target_memory_id = target_memory_id
        self.consolidation_response = consolidation_response

    def complete(self, prompt: str) -> str:
        if "EXISTING MEMORIES:" in prompt:
            return json.dumps(
                {"action": self.action, "target_memory_id": self.target_memory_id, "confidence": 0.9, "reasoning": "x"}
            )
        if "Graph Triple Extractor" in prompt:
            return "[]"
        if "MEMORIES TO CONSOLIDATE" in prompt:
            return self.consolidation_response or json.dumps({"content": "c", "confidence": 0.9, "reasoning": "r"})
        raise AssertionError(f"unexpected prompt: {prompt[:60]!r}")


class OutageGraphStore(InMemoryGraphStore):
    """Neo4j that is down until `.up = True`."""

    def __init__(self) -> None:
        super().__init__()
        self.up = False

    def upsert_entity(self, name, scope=None):
        if not self.up:
            raise ConnectionError("neo4j: connection refused")
        super().upsert_entity(name, scope)

    def upsert_relationship(self, source, relation, target, scope=None):
        if not self.up:
            raise ConnectionError("neo4j: connection refused")
        super().upsert_relationship(source, relation, target, scope)

    def mark_historical(self, source, relation, target, scope=None):
        if not self.up:
            raise ConnectionError("neo4j: connection refused")
        super().mark_historical(source, relation, target, scope)


class OutageDocumentStore:
    def __init__(self) -> None:
        self.up = False
        self._docs = {}

    def _check(self):
        if not self.up:
            raise ConnectionError("openknowledge: connection refused")

    def get(self, slug, scope=None):
        self._check()
        return self._docs.get(slug)

    def save(self, document):
        self._check()
        self._docs[document.slug] = document
        return document

    def search(self, query, scope=None, limit=5):
        self._check()
        return list(self._docs.values())[:limit]


def _service(llm, graph_store=None, document_store=None, job_store=None, sync_mode="eager", tracer=None):
    return AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=graph_store or InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=llm,
        document_store=document_store,
        sync_job_store=job_store,
        sync_mode=sync_mode,
        tracer=tracer or trace.Tracer(sinks=[]),
    )


def _experience(text, scope, event_type=EventType.AGENT_MESSAGE):
    return Experience(scope=scope, events=[Event(event_type=event_type)], output=text)


def test_observe_trace_records_the_full_pipeline():
    sink = trace.InMemoryTraceSink()
    scope = MemoryScope.of(tenant_id="t1", project_id="p")
    service = _service(ScriptedLLM(), tracer=trace.Tracer(sinks=[sink]))

    memory = service.observe(_experience("Aftermind uses PostgreSQL", scope))

    t = sink.recent(operation="observe")[0].to_dict()
    assert t["scope"] == scope.key()
    assert t["candidate_count"] == 1
    assert t["reconciliation_action"] == "create"
    assert t["sqlite_write"] == "ok"
    assert t["memory_id"] == memory.memory_id
    assert t["neo4j_sync"] == "ok"
    assert t["openknowledge_sync"] == "skipped"  # no document store wired
    assert t["checkpoint_created"] is False
    assert t["llm_calls"] == 1  # reconcile only; regex handled the triple
    assert t["llm_latency_ms"] >= 0
    assert {s["name"] for s in t["spans"]} >= {"reconcile", "sqlite.transaction", "sync.graph_sync"}


def test_neo4j_outage_keeps_the_memory_and_leaves_a_pending_job():
    sink = trace.InMemoryTraceSink()
    scope = MemoryScope.of(tenant_id="t1")
    graph, jobs = OutageGraphStore(), InMemorySyncJobStore()
    service = _service(ScriptedLLM(), graph_store=graph, job_store=jobs, tracer=trace.Tracer(sinks=[sink]))

    memory = service.observe(_experience("Aftermind uses PostgreSQL", scope))

    assert memory is not None
    assert service.knowledge_store.get(memory.memory_id) is not None  # canonical write survived
    t = sink.recent(operation="observe")[0].fields
    assert t["sqlite_write"] == "ok"
    assert t["neo4j_sync"] == "pending"
    pending = jobs.list_jobs(status=SyncJobStatus.PENDING)
    assert len(pending) == 1
    assert pending[0].kind == SyncJobKind.GRAPH_SYNC
    assert pending[0].payload["memory_id"] == memory.memory_id
    assert pending[0].trace_id == sink.recent(operation="observe")[0].trace_id
    assert graph.find_related("Aftermind", scope=scope) == []


def test_pending_graph_sync_resumes_once_neo4j_is_back():
    scope = MemoryScope.of(tenant_id="t1")
    graph, jobs = OutageGraphStore(), InMemorySyncJobStore()
    service = _service(ScriptedLLM(), graph_store=graph, job_store=jobs)
    service.observe(_experience("Aftermind uses PostgreSQL", scope))

    graph.up = True
    worker = SyncWorker(jobs, service.sync, tracer=trace.Tracer(sinks=[]), stale_running_seconds=0)
    from datetime import datetime, timedelta, timezone

    result = worker.run_once(now=datetime.now(timezone.utc) + timedelta(minutes=10))

    assert result["ok"] == 1
    assert graph.find_related("Aftermind", scope=scope) == ["PostgreSQL"]
    assert jobs.counts()["pending"] == 0


def test_openknowledge_outage_is_isolated_and_recall_still_works():
    sink = trace.InMemoryTraceSink()
    scope = MemoryScope.of(tenant_id="t1", project_id="p")
    docs, jobs = OutageDocumentStore(), InMemorySyncJobStore()
    llm = ScriptedLLM()
    service = _service(llm, document_store=docs, job_store=jobs, tracer=trace.Tracer(sinks=[sink]))
    old = service.observe(_experience("Aftermind uses SQLite", scope))
    # A lone memory never reaches OpenKnowledge (no cluster to consolidate),
    # so that first observe is fine even with the store down.
    assert sink.recent(operation="observe")[0].fields["openknowledge_sync"] == "ok"

    # Superseding it must refresh the stale page — which needs OpenKnowledge.
    llm.action, llm.target_memory_id = "supersede", old.memory_id
    memory = service.observe(_experience("Aftermind uses PostgreSQL", scope))

    assert memory is not None
    t = sink.recent(operation="observe")[0].fields
    assert t["sqlite_write"] == "ok"
    assert t["neo4j_sync"] == "ok"
    assert t["openknowledge_sync"] == "pending"
    pending = jobs.list_jobs(status=SyncJobStatus.PENDING)
    assert [j.kind for j in pending] == [SyncJobKind.KNOWLEDGE_RECONSOLIDATE]
    assert "openknowledge" in pending[0].last_error

    result = service.recall(RecallQuery(scope=scope, text="What does Aftermind use?"))
    assert "PostgreSQL" in result.context
    r = sink.recent(operation="recall")[0].fields
    assert r["openknowledge_search"] == "failed"
    assert "sqlite" in r["recall_sources"]


def test_supersede_enqueues_mark_stale_and_reconsolidate_jobs():
    scope = MemoryScope.of(tenant_id="t1", project_id="p")
    docs, jobs = OutageDocumentStore(), InMemorySyncJobStore()
    docs.up = True
    llm = ScriptedLLM()
    service = _service(llm, document_store=docs, job_store=jobs)
    old = service.observe(_experience("Billing uses Redis", scope))

    llm.action, llm.target_memory_id = "supersede", old.memory_id
    service.observe(_experience("Billing uses RabbitMQ", scope))

    kinds = sorted(j.kind.value for j in jobs.list_jobs(limit=100))
    assert kinds.count(SyncJobKind.GRAPH_MARK_STALE.value) == 1
    assert kinds.count(SyncJobKind.KNOWLEDGE_RECONSOLIDATE.value) == 1
    assert kinds.count(SyncJobKind.GRAPH_SYNC.value) == 2
    assert jobs.counts()["done"] == len(kinds)
    assert service.graph_store.find_related("Billing", scope=scope) == ["RabbitMQ"]
    assert service.graph_store.find_historical_relationships("Billing", scope=scope)[0][2] == "Redis"


def test_background_mode_defers_all_secondary_writes_to_the_worker():
    scope = MemoryScope.of(tenant_id="t1")
    jobs = InMemorySyncJobStore()
    service = _service(ScriptedLLM(), job_store=jobs, sync_mode=BACKGROUND)

    service.observe(_experience("Aftermind uses PostgreSQL", scope))

    assert service.graph_store.find_related("Aftermind", scope=scope) == []
    assert jobs.counts()["pending"] == 1
    SyncWorker(jobs, service.sync, tracer=trace.Tracer(sinks=[])).drain()
    assert service.graph_store.find_related("Aftermind", scope=scope) == ["PostgreSQL"]


def test_retried_graph_sync_does_not_duplicate_edges():
    scope = MemoryScope.of(tenant_id="t1")
    jobs = InMemorySyncJobStore()
    service = _service(ScriptedLLM(), job_store=jobs)
    memory = service.observe(_experience("Aftermind uses PostgreSQL", scope))

    service.sync.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": memory.memory_id}, scope)

    assert service.graph_store.find_related("Aftermind", scope=scope) == ["PostgreSQL"]


def test_handlers_tolerate_a_memory_deleted_before_the_job_ran():
    jobs = InMemorySyncJobStore()
    service = _service(ScriptedLLM(), job_store=jobs)
    assert service.sync.dispatch(SyncJobKind.GRAPH_SYNC, {"memory_id": "gone"}) == trace.OK


def test_recall_trace_lists_sources_and_counts():
    sink = trace.InMemoryTraceSink()
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(), tracer=trace.Tracer(sinks=[sink]))
    service.observe(_experience("Aftermind uses PostgreSQL", scope))
    service.checkpoint(scope=scope, goal="ship it")

    service.recall(RecallQuery(scope=scope, text="What database does Aftermind use?"))

    t = sink.recent(operation="recall")[0].to_dict()
    assert set(t["recall_sources"]) >= {"checkpoint", "sqlite"}
    assert t["returned_count"] == 1
    assert t["context_chars"] > 0
    assert t["latency_ms"] is not None


def test_recall_degrades_to_memories_only_when_the_graph_store_is_down():
    class DownReads(InMemoryGraphStore):
        def find_related(self, entity, scope=None, limit=5):
            raise ConnectionError("neo4j down")

    sink = trace.InMemoryTraceSink()
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(), graph_store=DownReads(), tracer=trace.Tracer(sinks=[sink]))
    service.observe(_experience("Aftermind uses PostgreSQL", scope))

    result = service.recall(RecallQuery(scope=scope, text="What database does Aftermind use?"))

    assert "PostgreSQL" in result.context
    assert result.related_entities == ()
    r = sink.recent(operation="recall")[0]
    assert r.status == trace.OK
    assert r.fields["graph_search"] == "failed"


def test_observe_records_admission_rejections_and_still_checkpoints_milestones():
    sink = trace.InMemoryTraceSink()
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(), tracer=trace.Tracer(sinks=[sink]))

    assert service.observe(_experience("also commit and push", scope)) is None
    assert sink.recent(operation="observe")[0].fields["admission"] == "rejected:directive"
    assert service.observe(_experience('Tool Bash result: {"stdout": "ok"}', scope, EventType.TOOL_COMPLETED)) is None
    assert sink.recent(operation="observe")[0].fields["admission"] == "rejected:tool_output"

    # A milestone with nothing memory-worthy in its text still checkpoints.
    assert service.observe(_experience("ok done", scope, EventType.TASK_COMPLETED)) is None
    assert sink.recent(operation="observe")[0].fields["checkpoint_created"] is True


def test_observe_llm_admission_mode_stores_each_extracted_fact():
    class AdmittingLLM(ScriptedLLM):
        def complete(self, prompt):
            if "ADMISSION REVIEW" in prompt:
                return json.dumps(
                    [
                        {"content": "The billing worker uses RabbitMQ.", "usefulness": 0.9, "durability": 0.9, "confidence": 0.9},
                        {"content": "Billing retries failed messages three times.", "usefulness": 0.8, "durability": 0.8},
                        {"content": "The deploy is running right now.", "usefulness": 0.9, "durability": 0.1},
                    ]
                )
            return super().complete(prompt)

    sink = trace.InMemoryTraceSink()
    scope = MemoryScope.of(tenant_id="t1")
    service = AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=AdmittingLLM(),
        admission_mode="llm",
        tracer=trace.Tracer(sinks=[sink]),
    )
    long_text = "Codex here: after a long discussion " + "about the queue " * 40 + "we settled on RabbitMQ with three retries; deploy is running."

    first = service.observe(_experience(long_text, scope))

    t = sink.recent(operation="observe")[0].fields
    assert first is not None
    assert t["admission"] == "llm"
    assert t["candidate_count"] == 2
    assert len(t["memory_ids"]) == 2
    stored = {m.content for m in service.knowledge_store.list_all(scope=scope)}
    assert stored == {"The billing worker uses RabbitMQ.", "Billing retries failed messages three times."}


def test_rules_mode_never_stores_overlong_text_verbatim():
    sink = trace.InMemoryTraceSink()
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(), tracer=trace.Tracer(sinks=[sink]))
    assert service.observe(_experience("We decided many things today. " * 40, scope)) is None
    assert sink.recent(operation="observe")[0].fields["admission"] == "rejected:needs_llm_extraction"
