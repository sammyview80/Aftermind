import json

from core.facade import AftermindService
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope
from providers.inmemory.store import (
    InMemoryCheckpointStore,
    InMemoryGraphStore,
    InMemoryKnowledgeStore,
    InMemoryLifecycleStore,
)


class ScriptedLLM:
    def __init__(self, action: str = "create", target_memory_id=None) -> None:
        self.action = action
        self.target_memory_id = target_memory_id

    def complete(self, prompt: str) -> str:
        if "EXISTING MEMORIES:" in prompt:
            return json.dumps(
                {"action": self.action, "target_memory_id": self.target_memory_id, "confidence": 0.9, "reasoning": "x"}
            )
        raise AssertionError(f"unexpected prompt: {prompt[:60]!r}")


def _service(llm) -> AftermindService:
    return AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=llm,
    )


def _experience(text: str, scope=None):
    from domain.enums.event_type import EventType
    from domain.models.event import Event
    from domain.models.experience import Experience

    return Experience(scope=scope, events=[Event(event_type=EventType.AGENT_MESSAGE)], output=text)


def test_observe_creates_a_memory_and_lifecycle_record():
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(action="create"))

    memory = service.observe(_experience("Team uses PostgreSQL for storage", scope))

    assert memory is not None
    assert memory.content == "Team uses PostgreSQL for storage"
    assert service.knowledge_store.get(memory.memory_id) is memory


def test_observe_returns_none_for_trivial_content():
    service = _service(ScriptedLLM())
    assert service.observe(_experience("okay thanks")) is None


def test_observe_supersede_archives_the_evidence_memorys_lifecycle():
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(action="create"))
    old = service.observe(_experience("Team uses Redis for the message queue", scope))
    assert old is not None

    service_supersede = _service(ScriptedLLM(action="supersede", target_memory_id=old.memory_id))
    service_supersede.knowledge_store.save(old)  # share the same store state
    new = service_supersede.observe(_experience("Team uses RabbitMQ for the message queue", scope))

    assert new is not None
    stale = service_supersede.knowledge_store.get(old.memory_id)
    assert stale.superseded_by == new.memory_id


def test_recall_returns_ranked_memories_and_context():
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(action="create"))
    memory = service.observe(_experience("The team's primary database is Postgres", scope))
    assert memory is not None

    result = service.recall(RecallQuery(scope=scope, text="What database do we use?"))

    assert memory in result.memories
    assert "Postgres" in result.context


def test_checkpoint_and_latest_checkpoint_round_trip():
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM())

    checkpoint = service.checkpoint(scope=scope, goal="Build login flow", current="wiring session handling")

    assert service.latest_checkpoint(scope) is checkpoint
    assert checkpoint.goal == "Build login flow"


def test_search_is_direct_and_bypasses_ranking_and_checkpoint():
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(action="create"))
    memory = service.observe(_experience("Aftermind uses Graphiti for graph memory", scope))

    results = service.search("Graphiti", scope=scope)

    assert memory in results


def test_observe_syncs_entities_and_relationships_to_the_graph_store():
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(action="create"))

    service.observe(_experience("Aftermind uses PostgreSQL", scope))

    assert service.graph_store.find_related("Aftermind", scope=scope) == ["PostgreSQL"]
