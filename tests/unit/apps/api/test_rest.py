import json

from fastapi.testclient import TestClient

from apps.api.deps import get_service
from apps.api.main import app
from core.facade import AftermindService
from providers.inmemory.store import (
    InMemoryCheckpointStore,
    InMemoryGraphStore,
    InMemoryKnowledgeStore,
    InMemoryLifecycleStore,
)


class ScriptedLLM:
    def complete(self, prompt: str) -> str:
        return json.dumps({"action": "create", "target_memory_id": None, "confidence": 0.9, "reasoning": "x"})


_shared_service = AftermindService(
    knowledge_store=InMemoryKnowledgeStore(),
    graph_store=InMemoryGraphStore(),
    checkpoint_store=InMemoryCheckpointStore(),
    lifecycle_store=InMemoryLifecycleStore(),
    llm_provider=ScriptedLLM(),
)

app.dependency_overrides[get_service] = lambda: _shared_service
client = TestClient(app)


def test_health():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_observe_then_search_then_recall():
    scope = {"tenant_id": "t1"}

    observe_response = client.post(
        "/observe", json={"scope": {"levels": scope}, "output": "Team uses PostgreSQL for storage"}
    )
    assert observe_response.status_code == 200
    body = observe_response.json()
    assert body["created"] is True
    assert body["content"] == "Team uses PostgreSQL for storage"

    search_response = client.post("/search", json={"scope": {"levels": scope}, "query": "PostgreSQL"})
    assert search_response.status_code == 200
    assert len(search_response.json()["memories"]) == 1

    recall_response = client.post(
        "/recall", json={"scope": {"levels": scope}, "text": "What does the team use for storage?"}
    )
    assert recall_response.status_code == 200
    assert "PostgreSQL" in recall_response.json()["context"]


def test_checkpoint_create_and_latest():
    scope = {"tenant_id": "t2"}

    create_response = client.post(
        "/checkpoint", json={"scope": {"levels": scope}, "goal": "Build login flow", "current": "wiring session handling"}
    )
    assert create_response.status_code == 200
    assert create_response.json()["goal"] == "Build login flow"

    latest_response = client.post("/checkpoint/latest", json={"scope": {"levels": scope}})
    assert latest_response.status_code == 200
    assert latest_response.json()["found"] is True
    assert latest_response.json()["goal"] == "Build login flow"


def test_latest_checkpoint_not_found():
    response = client.post("/checkpoint/latest", json={"scope": {"levels": {"tenant_id": "nonexistent"}}})
    assert response.status_code == 200
    assert response.json()["found"] is False


def test_observe_trivial_content_is_not_created():
    response = client.post("/observe", json={"scope": {"levels": {"tenant_id": "t3"}}, "output": "okay thanks"})
    assert response.status_code == 200
    assert response.json()["created"] is False


class FakeDocumentStore:
    def __init__(self) -> None:
        self._docs = {}

    def get(self, slug, scope=None):
        return self._docs.get(slug)

    def save(self, document):
        self._docs[document.slug] = document
        return document

    def search(self, query, scope=None, limit=5):
        return []


class RoutingScriptedLLM:
    def complete(self, prompt: str) -> str:
        if "MEMORIES TO CONSOLIDATE" in prompt:
            return json.dumps(
                {
                    "content": "Client prefers premium dark visual styles, especially black and gold.",
                    "confidence": 0.9,
                    "reasoning": "Consistent pattern.",
                }
            )
        if "EXISTING MEMORIES:" in prompt:
            return json.dumps({"action": "create", "target_memory_id": None, "confidence": 0.9, "reasoning": "x"})
        return "[]"


def test_consolidate_writes_to_document_store():
    document_store = FakeDocumentStore()
    consolidation_service = AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=RoutingScriptedLLM(),
        document_store=document_store,
    )
    original_override = app.dependency_overrides[get_service]
    app.dependency_overrides[get_service] = lambda: consolidation_service
    try:
        scope = {"tenant_id": "consolidate-rest"}
        for text in ["Client rejected bright blue", "Client prefers dark layouts", "Client approved black and gold"]:
            client.post("/observe", json={"scope": {"levels": scope}, "output": text})

        response = client.post(
            "/consolidate", json={"scope": {"levels": scope}, "slug": "client-prefs", "min_group_size": 3}
        )
        assert response.status_code == 200
        body = response.json()
        assert len(body["consolidated"]) == 1
        assert body["consolidated"][0]["accepted"] is True
        assert body["consolidated"][0]["document_slug"] == "client-prefs"
    finally:
        app.dependency_overrides[get_service] = original_override
