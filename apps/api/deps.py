import os
import sys
from functools import lru_cache

from core.facade import AftermindService
from providers.inmemory.store import InMemoryGraphStore
from providers.llm.openrouter import OpenRouterProvider
from providers.sqlite.checkpoint_store import SqliteCheckpointStore
from providers.sqlite.client import DEFAULT_DB_PATH, SqliteClient
from providers.sqlite.decision_store import SqliteDecisionStore
from providers.sqlite.episode_store import SqliteEpisodeStore
from providers.sqlite.knowledge_store import SqliteKnowledgeStore
from providers.sqlite.lifecycle_store import SqliteLifecycleStore

DEFAULT_NEO4J_URI = "bolt://localhost:7687"
DEFAULT_NEO4J_USER = "neo4j"


class _LazyLLMProvider:
    """Defers OpenRouterProvider construction (and its LLM_API_KEY/
    LLM_MODEL validation) until the first `.complete()` call, so routes
    that never touch the LLM (health, recall, checkpoint, search) don't
    require an API key to be configured."""

    def __init__(self) -> None:
        self._provider = None

    def complete(self, prompt: str) -> str:
        if self._provider is None:
            self._provider = OpenRouterProvider()
        return self._provider.complete(prompt)


def _build_graph_store():
    """Phase 2 durable backend: real graphiti-core writes + Cypher reads
    against Neo4j (NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD). Falls back to
    the in-process InMemoryGraphStore — printing why — if graphiti-core/
    neo4j aren't installed or the database isn't reachable, so the rest
    of the service still starts."""
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        print("NEO4J_PASSWORD not set — GraphStore falling back to in-memory.", file=sys.stderr)
        return InMemoryGraphStore()

    try:
        from providers.graphiti.client import Neo4jClient
        from providers.graphiti.graphiti_client import GraphitiWriter
        from providers.graphiti.store import GraphitiStore

        uri = os.environ.get("NEO4J_URI", DEFAULT_NEO4J_URI)
        user = os.environ.get("NEO4J_USER", DEFAULT_NEO4J_USER)
        writer = GraphitiWriter(uri, user, password)
        client = Neo4jClient(uri, user, password)
        return GraphitiStore(writer, client)
    except Exception as exc:  # noqa: BLE001 - infra may simply not be up yet
        print(f"GraphStore falling back to in-memory: {exc}", file=sys.stderr)
        return InMemoryGraphStore()


@lru_cache(maxsize=1)
def get_document_store():
    """Phase 3 durable backend: OpenKnowledge for consolidated, human-
    readable knowledge (the Consolidation Engine's output — not every
    StoredMemory). OPENKNOWLEDGE_URL points at a running `ok start` / OK
    Desktop server; unset falls back to a local markdown directory."""
    from providers.openknowledge.store import OpenKnowledgeStore

    openknowledge_url = os.environ.get("OPENKNOWLEDGE_URL")
    if openknowledge_url:
        from providers.openknowledge.remote_client import RemoteOpenKnowledgeClient

        return OpenKnowledgeStore(RemoteOpenKnowledgeClient(openknowledge_url))

    from providers.openknowledge.client import LocalMarkdownClient

    return OpenKnowledgeStore(LocalMarkdownClient())


@lru_cache(maxsize=1)
def get_service() -> AftermindService:
    """The process-wide AftermindService singleton, built once on first
    use.

    Phase 1 durable backend: SQLite (experiences, memories, checkpoints,
    memory decisions, lifecycle metadata), configured via DATABASE_PATH
    (default ./aftermind.db).
    Phase 2 durable backend: Graphiti + Neo4j for entities/relationships,
    configured via NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD.
    Phase 3 durable backend: OpenKnowledge for consolidated knowledge,
    configured via OPENKNOWLEDGE_URL (see get_document_store()).
    """
    db_path = os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)
    client = SqliteClient(db_path)

    return AftermindService(
        knowledge_store=SqliteKnowledgeStore(client),
        graph_store=_build_graph_store(),
        checkpoint_store=SqliteCheckpointStore(client),
        lifecycle_store=SqliteLifecycleStore(client),
        llm_provider=_LazyLLMProvider(),
        episode_store=SqliteEpisodeStore(client),
        decision_store=SqliteDecisionStore(client),
        document_store=get_document_store(),
    )
