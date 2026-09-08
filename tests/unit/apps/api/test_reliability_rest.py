import json

import pytest
from fastapi.testclient import TestClient

from apps.api.deps import get_service, get_sync_worker, get_trace_sink
from apps.api.main import app
from core.facade import AftermindService
from core.observability import trace
from core.sync.worker import SyncWorker
from providers.inmemory.store import (
    InMemoryCheckpointStore,
    InMemoryGraphStore,
    InMemoryKnowledgeStore,
    InMemoryLifecycleStore,
    InMemorySyncJobStore,
)


class ScriptedLLM:
    def complete(self, prompt: str) -> str:
        if "EXISTING MEMORIES:" in prompt:
            return json.dumps({"action": "create", "target_memory_id": None, "confidence": 0.9, "reasoning": "x"})
        return "[]"


class DownGraphStore(InMemoryGraphStore):
    def upsert_entity(self, name, scope=None):
        raise ConnectionError("neo4j down")

    def upsert_relationship(self, source, relation, target, scope=None):
        raise ConnectionError("neo4j down")


_sink = trace.InMemoryTraceSink()
_jobs = InMemorySyncJobStore()
_service = AftermindService(
    knowledge_store=InMemoryKnowledgeStore(),
    graph_store=DownGraphStore(),
    checkpoint_store=InMemoryCheckpointStore(),
    lifecycle_store=InMemoryLifecycleStore(),
    llm_provider=ScriptedLLM(),
    sync_job_store=_jobs,
    tracer=trace.Tracer(sinks=[_sink]),
)
_worker = SyncWorker(_jobs, _service.sync, tracer=trace.Tracer(sinks=[_sink]))

client = TestClient(app)


@pytest.fixture(autouse=True)
def _override_dependencies():
    # Installed per test (not at import) because other REST test modules
    # also set app.dependency_overrides at import time and the last import
    # would otherwise win for every module.
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_service] = lambda: _service
    app.dependency_overrides[get_sync_worker] = lambda: _worker
    app.dependency_overrides[get_trace_sink] = lambda: _sink
    try:
        yield
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_observe_returns_observe_id_and_per_store_sync_status():
    response = client.post(
        "/observe", json={"scope": {"levels": {"tenant_id": "rel"}}, "output": "Aftermind uses PostgreSQL"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["reconciliation_action"] == "create"
    assert body["sync"] == {"sqlite_write": "ok", "neo4j_sync": "pending", "openknowledge_sync": "skipped"}
    assert response.headers["X-Aftermind-Trace-Id"] == body["observe_id"]

    # The same trace is retrievable, with its pipeline fields.
    got = client.get(f"/traces/{body['observe_id']}").json()
    assert got["operation"] == "observe"
    assert got["memory_id"] == body["memory_id"]
    assert got["neo4j_sync"] == "pending"


def test_recall_returns_trace_id_and_sources():
    response = client.post("/recall", json={"scope": {"levels": {"tenant_id": "rel"}}, "text": "Aftermind database"})
    body = response.json()
    assert "PostgreSQL" in body["context"]
    assert body["trace_id"]
    assert "sqlite" in body["recall_sources"]
    assert body["recall_latency_ms"] is not None


def test_sync_status_shows_backlog_and_run_retries_it():
    status = client.get("/maintenance/sync").json()
    assert status["durable"] is True
    assert status["mode"] == "eager"
    assert status["counts"]["pending"] >= 1
    assert status["jobs"][0]["kind"] == "graph_sync"
    assert "neo4j down" in status["jobs"][0]["last_error"]

    # Nothing is due yet (backoff), so a run processes nothing — and no error.
    assert client.post("/maintenance/sync/run").status_code == 200


def test_ready_reports_degraded_only_for_dead_jobs_and_is_still_200():
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("ok", "degraded")
    assert body["checks"]["sync_jobs"]["pending"] >= 1


def test_liveness_is_unchanged():
    assert client.get("/health").json() == {"status": "ok"}


def test_traces_endpoint_lists_recent_operations_newest_first():
    body = client.get("/traces?operation=observe").json()
    assert body["traces"]
    assert all(t["operation"] == "observe" for t in body["traces"])


def test_unknown_trace_is_404():
    assert client.get("/traces/nope").status_code == 404


def test_config_endpoint_redacts_secrets(monkeypatch):
    from apps.api import deps

    monkeypatch.setenv("LLM_API_KEY", "sk-secret")
    deps.get_settings.cache_clear()
    body = client.get("/config").json()
    assert body["llm_api_key"] == "***"
    assert "sk-secret" not in json.dumps(body)
    deps.get_settings.cache_clear()
