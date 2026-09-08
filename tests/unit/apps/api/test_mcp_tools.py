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
    assert tools.memory_observe(service, scope={"tenant_id": "t1"}, output="okay thanks") == {"created": False}


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
