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
    def __init__(self, action: str = "create", target_memory_id=None, consolidation_response=None) -> None:
        self.action = action
        self.target_memory_id = target_memory_id
        self.consolidation_response = consolidation_response

    def complete(self, prompt: str) -> str:
        if "EXISTING MEMORIES:" in prompt:
            return json.dumps(
                {"action": self.action, "target_memory_id": self.target_memory_id, "confidence": 0.9, "reasoning": "x"}
            )
        if "Graph Triple Extractor" in prompt:
            return "[]"  # graph-extraction correctness is triple_extractor's own tests' job
        if "MEMORIES TO CONSOLIDATE" in prompt:
            if self.consolidation_response is None:
                raise AssertionError("unexpected consolidation call")
            return self.consolidation_response
        raise AssertionError(f"unexpected prompt: {prompt[:60]!r}")


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


def _service(llm, document_store=None) -> AftermindService:
    return AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=llm,
        document_store=document_store,
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


def test_consolidate_raises_without_a_document_store():
    service = _service(ScriptedLLM(action="create"))
    try:
        service.consolidate()
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "DocumentStore" in str(exc)


def test_consolidate_clusters_related_memories_and_writes_to_document_store():
    scope = MemoryScope.of(tenant_id="t1")
    consolidation_response = json.dumps(
        {
            "content": "Client prefers premium dark visual styles, especially black and gold.",
            "confidence": 0.9,
            "reasoning": "Consistent pattern across memories.",
        }
    )
    document_store = FakeDocumentStore()
    service = _service(ScriptedLLM(action="create", consolidation_response=consolidation_response), document_store)

    for text in ["Client rejected bright blue", "Client prefers dark layouts", "Client approved black and gold"]:
        assert service.observe(_experience(text, scope)) is not None

    results = service.consolidate(scope=scope, slug="client-prefs", title="Client Preferences", min_group_size=3)

    assert len(results) == 1
    assert results[0].accepted is True
    assert results[0].document_slug == "client-prefs"
    document = document_store.get("client-prefs")
    assert "black and gold" in document.to_markdown()
    assert len(document.source_memory_ids) == 3


def test_consolidate_below_threshold_produces_no_results():
    scope = MemoryScope.of(tenant_id="t1")
    document_store = FakeDocumentStore()
    service = _service(ScriptedLLM(action="create"), document_store)

    service.observe(_experience("Client prefers dark layouts", scope))

    assert service.consolidate(scope=scope, min_group_size=3) == []
