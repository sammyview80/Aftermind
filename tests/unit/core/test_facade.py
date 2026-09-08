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
    def __init__(
        self, action: str = "create", target_memory_id=None, consolidation_response=None, checkpoint_response=None
    ) -> None:
        self.action = action
        self.target_memory_id = target_memory_id
        self.consolidation_response = consolidation_response
        self.checkpoint_response = checkpoint_response

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
        if "PREVIOUS CHECKPOINT" in prompt:
            if self.checkpoint_response is None:
                raise AssertionError("unexpected checkpoint-summarizer call")
            return self.checkpoint_response
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
        query_words = set(query.lower().split())

        def matches(document) -> bool:
            text = (document.title + " " + " ".join(s.heading + " " + s.body for s in document.sections)).lower()
            return bool(query_words & set(text.split()))

        return [d for d in self._docs.values() if matches(d)][:limit]


def _service(llm, document_store=None) -> AftermindService:
    return AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=llm,
        document_store=document_store,
    )


def _experience(text: str, scope=None, event_type=None):
    from domain.enums.event_type import EventType
    from domain.models.event import Event
    from domain.models.experience import Experience

    event_type = event_type or EventType.AGENT_MESSAGE
    return Experience(scope=scope, events=[Event(event_type=event_type)], output=text)


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


def test_checkpoint_from_text_summarizes_freeform_conversation():
    scope = MemoryScope.of(tenant_id="t1", session_id="s1")
    checkpoint_response = json.dumps(
        {
            "goal": "Integrate OpenKnowledge",
            "completed": ["SQLite integration", "Neo4j integration"],
            "current": "Wiring automatic checkpointing",
            "blocked_by": [],
            "next_steps": ["Wire automatic checkpointing"],
        }
    )
    service = _service(ScriptedLLM(checkpoint_response=checkpoint_response))

    checkpoint = service.checkpoint_from_text(
        scope=scope,
        text="We finished SQLite and Neo4j integration. Next we need to wire automatic checkpointing.",
    )

    assert checkpoint.goal == "Integrate OpenKnowledge"
    assert checkpoint.completed == ("SQLite integration", "Neo4j integration")
    assert checkpoint.next_steps == ("Wire automatic checkpointing",)
    assert service.latest_checkpoint(scope) is checkpoint


def test_checkpoint_from_text_returns_none_for_empty_text():
    service = _service(ScriptedLLM())
    assert service.checkpoint_from_text(scope=MemoryScope.of(tenant_id="t1"), text="") is None
    assert service.checkpoint_from_text(scope=MemoryScope.of(tenant_id="t1"), text="   ") is None


def test_checkpoint_from_text_uses_previous_goal_as_continuity_context():
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM())
    service.checkpoint(scope=scope, goal="Integrate OpenKnowledge")

    seen_prompts = []
    original_complete = service._checkpoint_summarizer._llm.complete

    def capturing_complete(prompt):
        seen_prompts.append(prompt)
        return json.dumps({"goal": "Integrate OpenKnowledge", "completed": [], "current": "x", "blocked_by": [], "next_steps": []})

    service._checkpoint_summarizer._llm.complete = capturing_complete
    service.checkpoint_from_text(scope=scope, text="Still working on it.")

    assert "Integrate OpenKnowledge" in seen_prompts[0]


def test_observe_auto_consolidates_once_five_related_memories_exist():
    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    consolidation_response = json.dumps(
        {
            "content": "SQLite is Aftermind's canonical local memory store.",
            "confidence": 0.9,
            "reasoning": "Five consistent statements about Aftermind's SQLite storage.",
        }
    )
    document_store = FakeDocumentStore()
    service = _service(ScriptedLLM(action="create", consolidation_response=consolidation_response), document_store)

    statements = [
        "Aftermind uses SQLite locally",
        "SQLite is canonical for Aftermind",
        "Aftermind stores memory in SQLite",
        "SQLite powers Aftermind memory",
        "Aftermind relies on SQLite storage",
    ]
    for text in statements[:-1]:
        service.observe(_experience(text, scope))
    assert document_store.get("projects/aftermind/knowledge") is None  # not yet, only 4 related so far

    service.observe(_experience(statements[-1], scope))  # 5th related memory crosses the auto threshold

    document = document_store.get("projects/aftermind/knowledge", scope=scope)
    assert document is not None
    assert "canonical local memory store" in document.to_markdown()


def test_observe_does_not_auto_consolidate_plain_chat_below_threshold():
    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    document_store = FakeDocumentStore()
    service = _service(ScriptedLLM(action="create"), document_store)

    service.observe(_experience("Aftermind uses SQLite locally", scope))
    service.observe(_experience("SQLite is canonical for Aftermind", scope))

    assert document_store.get("projects/aftermind/knowledge") is None


def test_observe_auto_consolidates_on_confirmed_decision_with_fewer_memories():
    from domain.enums.event_type import EventType

    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    consolidation_response = json.dumps(
        {
            "content": "Aftermind switched canonical storage to PostgreSQL.",
            "confidence": 0.9,
            "reasoning": "Confirmed architecture decision.",
        }
    )
    document_store = FakeDocumentStore()
    service = _service(ScriptedLLM(action="create", consolidation_response=consolidation_response), document_store)

    service.observe(_experience("Aftermind uses PostgreSQL for storage", scope))
    service.observe(_experience("PostgreSQL is canonical for Aftermind", scope))
    # Third, decision-confirming memory pushes this 3-memory cluster over the
    # lower milestone bar (DEFAULT_MEMORY_COUNT_THRESHOLD) without needing 5.
    service.observe(_experience("PostgreSQL is Aftermind's storage", scope, event_type=EventType.DECISION_CONFIRMED))

    document = document_store.get("projects/aftermind/knowledge", scope=scope)
    assert document is not None
    assert "PostgreSQL" in document.to_markdown()


def test_reconsolidation_updates_existing_page_instead_of_creating_a_new_one():
    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    first_consolidation = json.dumps(
        {
            "content": "SQLite is Aftermind's canonical local memory store.",
            "confidence": 0.9,
            "reasoning": "Five consistent statements.",
        }
    )
    llm = ScriptedLLM(action="create", consolidation_response=first_consolidation)
    document_store = FakeDocumentStore()
    service = _service(llm, document_store)

    statements = [
        "Aftermind uses SQLite locally",
        "SQLite is canonical for Aftermind",
        "Aftermind stores memory in SQLite",
        "SQLite powers Aftermind memory",
        "Aftermind relies on SQLite storage",
    ]
    memories = [service.observe(_experience(text, scope)) for text in statements]
    assert all(memories)

    original = document_store.get("projects/aftermind/knowledge", scope=scope)
    assert original is not None
    original_topic = original.sections[0].heading
    assert original.version == 1

    # Now the team switches canonical storage — the first memory gets
    # superseded, which should refresh the *same* page/section rather
    # than minting a second document.
    llm.action = "supersede"
    llm.target_memory_id = memories[0].memory_id
    llm.consolidation_response = json.dumps(
        {
            "content": "Aftermind switched canonical storage from SQLite to PostgreSQL.",
            "confidence": 0.9,
            "reasoning": "Storage migration confirmed.",
        }
    )
    service.observe(_experience("Aftermind switched canonical storage from SQLite to PostgreSQL", scope))

    updated = document_store.get("projects/aftermind/knowledge", scope=scope)
    assert updated is not None
    assert updated.slug == original.slug
    assert len(document_store._docs) == 1  # never a second/duplicate page
    assert updated.sections[0].heading == original_topic
    assert "PostgreSQL" in updated.to_markdown()


def test_recall_fuses_sqlite_neo4j_openknowledge_and_checkpoint_into_one_context():
    """Milestone 5 acceptance scenario: billing switched Redis -> RabbitMQ,
    RabbitMQ belongs to payments architecture, an OpenKnowledge page
    documents billing architecture, and there's an active checkpoint on
    billing worker migration. One recall() call should fuse all four
    into one compact, labeled context — not four raw blobs."""
    from domain.models.knowledge_document import KnowledgeDocument, KnowledgeSection

    scope = MemoryScope.of(tenant_id="t1", project_id="billing")
    document_store = FakeDocumentStore()
    llm = ScriptedLLM(action="create")
    service = _service(llm, document_store)

    redis_memory = service.observe(_experience("Billing used Redis before", scope))
    assert redis_memory is not None

    llm.action = "supersede"
    llm.target_memory_id = redis_memory.memory_id
    rabbitmq_memory = service.observe(_experience("Billing now uses RabbitMQ", scope))
    assert rabbitmq_memory is not None

    service.graph_store.upsert_relationship("RabbitMQ", "part_of", "payments architecture", scope=scope.stable())

    document_store.save(
        KnowledgeDocument(
            scope=scope.stable(),
            slug=service._document_slug(scope.stable()),
            title="Billing Knowledge",
            sections=(KnowledgeSection(heading="Billing Architecture", body="Billing uses RabbitMQ for messaging."),),
        )
    )

    service.checkpoint(scope=scope, goal="Migrate billing workers", current="migrating billing workers")

    result = service.recall(
        RecallQuery(scope=scope, text="What RabbitMQ setup are we using for billing and what are we working on?")
    )

    assert "Billing now uses RabbitMQ" in result.context  # current fact
    assert "Billing used Redis before (superseded)" in result.context  # historical
    assert "RabbitMQ -[part_of]-> payments architecture" in result.context  # relationship
    assert "Billing Architecture" in result.context  # OpenKnowledge excerpt
    assert "Migrate billing workers" in result.context  # checkpoint
    # One package: every section present, not separate disjoint calls.
    for heading in ("## Where you left off", "## Current facts", "## Recent history", "## Relationships", "## From company knowledge"):
        assert heading in result.context


def test_milestone_6_supersede_updates_lifecycle_graph_and_recall():
    """Acceptance scenario: SQLite -> superseded, PostgreSQL -> active.
    Normal recall returns PostgreSQL only; the superseded fact and its
    graph relationship are preserved as history, not deleted."""
    scope = MemoryScope.of(tenant_id="t1", project_id="aftermind")
    llm = ScriptedLLM(action="create")
    service = _service(llm)

    sqlite_memory = service.observe(_experience("Aftermind uses SQLite", scope))
    assert sqlite_memory is not None

    # Recall it a few times before it's superseded -> reinforced.
    for _ in range(3):
        service.recall(RecallQuery(scope=scope, text="What database does Aftermind use?"))
    lifecycle_before = service._lifecycle._store.get(sqlite_memory.memory_id, scope=scope.stable())
    assert lifecycle_before.access_count >= 3

    llm.action = "supersede"
    llm.target_memory_id = sqlite_memory.memory_id
    postgres_memory = service.observe(_experience("Aftermind uses PostgreSQL", scope))
    assert postgres_memory is not None

    stale_lifecycle = service._lifecycle._store.get(sqlite_memory.memory_id, scope=scope.stable())
    assert stale_lifecycle.status.value == "archived"

    # Normal recall: current fact only, PostgreSQL.
    current = service.recall(RecallQuery(scope=scope, text="What database does Aftermind use?"))
    assert "PostgreSQL" in current.context
    assert all(m.memory_id != sqlite_memory.memory_id for m in current.memories)

    # Historical question: SQLite still answerable via history.
    historical = service.recall(RecallQuery(scope=scope, text="What database did Aftermind previously use?"))
    assert "Aftermind uses SQLite" in historical.context
    assert "(superseded)" in historical.context

    # Neo4j: the old relationship is preserved but marked historical,
    # not surfaced by the normal (current) relationship lookup.
    stable_scope = scope.stable()
    current_rels = service.graph_store.find_relationships("Aftermind", scope=stable_scope)
    historical_rels = service.graph_store.find_historical_relationships("Aftermind", scope=stable_scope)
    assert any(target == "PostgreSQL" for _, _, target in current_rels)
    assert all(target != "SQLite" for _, _, target in current_rels)
    assert any(target == "SQLite" for _, _, target in historical_rels)


def test_archived_memory_is_excluded_from_normal_recall():
    scope = MemoryScope.of(tenant_id="t1")
    service = _service(ScriptedLLM(action="create"))
    memory = service.observe(_experience("Old fact nobody asked about again", scope))
    assert memory is not None

    from domain.enums.memory_status import MemoryStatus

    lifecycle = service._lifecycle._store.get(memory.memory_id, scope=scope.stable())
    from dataclasses import replace

    service._lifecycle._store.save(replace(lifecycle, status=MemoryStatus.ARCHIVED))

    result = service.recall(RecallQuery(scope=scope, text="Old fact nobody asked about again"))

    assert all(m.memory_id != memory.memory_id for m in result.memories)
