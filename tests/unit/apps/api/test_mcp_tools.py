import json

from apps.api.mcp import tools
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


def _service() -> AftermindService:
    return AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=ScriptedLLM(),
    )


def test_memory_observe_creates_and_returns_summary():
    service = _service()
    result = tools.memory_observe(service, scope={"tenant_id": "t1"}, output="Team uses PostgreSQL for storage")

    assert result["created"] is True
    assert result["content"] == "Team uses PostgreSQL for storage"
    assert "memory_id" in result


def test_memory_observe_trivial_content_not_created():
    service = _service()
    result = tools.memory_observe(service, scope={"tenant_id": "t1"}, output="okay thanks")
    assert result["created"] is False
    assert result["admission"].startswith("rejected:")


def test_memory_search_finds_observed_memory():
    service = _service()
    tools.memory_observe(service, scope={"tenant_id": "t1"}, output="Aftermind uses Graphiti for graph memory")

    result = tools.memory_search(service, scope={"tenant_id": "t1"}, query="Graphiti")

    assert len(result["memories"]) == 1
    assert "Graphiti" in result["memories"][0]["content"]


def test_memory_recall_includes_context():
    service = _service()
    tools.memory_observe(service, scope={"tenant_id": "t1"}, output="Team uses PostgreSQL for storage")

    result = tools.memory_recall(service, scope={"tenant_id": "t1"}, text="What does the team use for storage?")

    assert "PostgreSQL" in result["context"]


def test_memory_checkpoint_round_trips_through_facade():
    service = _service()
    result = tools.memory_checkpoint(service, scope={"tenant_id": "t1"}, goal="Build login flow")

    assert result["goal"] == "Build login flow"
    assert result["version"] == 1


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
        return "[]"  # graph triple extraction — not under test here


def test_memory_consolidate_writes_to_document_store():
    document_store = FakeDocumentStore()
    service = AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=RoutingScriptedLLM(),
        document_store=document_store,
    )
    scope = {"tenant_id": "t1"}
    for text in ["Client rejected bright blue", "Client prefers dark layouts", "Client approved black and gold"]:
        tools.memory_observe(service, scope=scope, output=text)

    result = tools.memory_consolidate(service, scope=scope, slug="client-prefs", min_group_size=3)

    assert len(result["consolidated"]) == 1
    assert result["consolidated"][0]["accepted"] is True
    assert result["consolidated"][0]["document_slug"] == "client-prefs"
    assert len(result["consolidated"][0]["source_memory_ids"]) == 3
