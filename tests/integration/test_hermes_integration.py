"""End-to-end test of the first real framework adapter:

    Hermes event/context -> event_mapper/scope_mapper -> AftermindService.observe()
    Hermes session finalize -> checkpoint_adapter -> AftermindService.checkpoint()
    Hermes recall request -> AftermindService.recall()

Fake LLM (deterministic, offline) stands in for the real reconciler
model; everything else is real wiring through HermesMemoryPlugin.
"""
import json

from core.facade import AftermindService
from integrations.hermes.plugin import HermesMemoryPlugin
from providers.inmemory.store import (
    InMemoryCheckpointStore,
    InMemoryGraphStore,
    InMemoryKnowledgeStore,
    InMemoryLifecycleStore,
)


class ScriptedLLM:
    def complete(self, prompt: str) -> str:
        return json.dumps({"action": "create", "target_memory_id": None, "confidence": 0.9, "reasoning": "x"})


def _plugin() -> HermesMemoryPlugin:
    service = AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=ScriptedLLM(),
    )
    return HermesMemoryPlugin(service)


def test_hermes_event_becomes_a_memory():
    plugin = _plugin()
    hermes_context = {"tenant_id": "t1", "project_id": "aftermind", "profile": "coder", "session_id": "s1"}

    result = plugin.on_event(
        {"id": "evt1", "type": "agent_message", "text": "Team uses PostgreSQL for storage"}, hermes_context
    )

    assert result["created"] is True
    assert result["content"] == "Team uses PostgreSQL for storage"


def test_hermes_session_finalize_produces_a_checkpoint_in_hermes_shape():
    plugin = _plugin()
    hermes_context = {"tenant_id": "t1", "profile": "coder", "session_id": "s1"}
    hermes_events = [
        {"type": "user_message", "text": "Build the login flow"},
        {"type": "tool_result", "tool": "repo_search", "result": "found auth module"},
        {"type": "agent_message", "text": "Login flow implemented"},
        {"type": "task_end", "success": True, "result": "tests passed"},
    ]

    checkpoint = plugin.on_session_finalize(hermes_context, hermes_events)

    assert checkpoint["goal"] == "Build the login flow"
    assert "found auth module" in checkpoint["completed"] or "tests passed" in checkpoint["completed"]
    assert checkpoint["current"] == "Login flow implemented"
    assert checkpoint["version"] == 1
    assert "blocked_by" in checkpoint  # Hermes-shaped, not "blockers"


def test_hermes_recall_request_returns_context_and_memories():
    plugin = _plugin()
    hermes_context = {"tenant_id": "t1", "profile": "coder", "session_id": "s1"}

    plugin.on_event(
        {"id": "evt1", "type": "agent_message", "text": "Team uses PostgreSQL for storage"}, hermes_context
    )

    result = plugin.on_recall_request(hermes_context, "What does the team use for storage?")

    assert len(result["memories"]) == 1
    assert "PostgreSQL" in result["context"]


def test_memory_persists_across_hermes_sessions_in_the_same_tenant():
    """The whole point of durable memory: what's learned in session s1
    must be recallable from a brand-new session s2 — a fact shouldn't be
    trapped behind the session_id it happened to be learned under."""
    plugin = _plugin()
    context_a = {"tenant_id": "t1", "profile": "coder", "session_id": "s1"}
    context_b = {"tenant_id": "t1", "profile": "coder", "session_id": "s2"}

    plugin.on_event({"type": "agent_message", "text": "Team uses PostgreSQL for storage"}, context_a)

    result = plugin.on_recall_request(context_b, "What does the team use for storage?")

    assert len(result["memories"]) == 1
    assert "PostgreSQL" in result["context"]


def test_events_from_different_tenants_stay_scoped_apart():
    plugin = _plugin()
    context_a = {"tenant_id": "t1", "profile": "coder", "session_id": "s1"}
    context_b = {"tenant_id": "t2", "profile": "coder", "session_id": "s1"}

    plugin.on_event({"type": "agent_message", "text": "Team uses PostgreSQL for storage"}, context_a)

    result = plugin.on_recall_request(context_b, "What does the team use for storage?")

    assert result["memories"] == []
