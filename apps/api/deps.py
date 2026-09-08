import os
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


@lru_cache(maxsize=1)
def get_service() -> AftermindService:
    """The process-wide AftermindService singleton, built once on first
    use.

    Phase 1 durable backend: SQLite (experiences, memories, checkpoints,
    memory decisions, lifecycle metadata), configured via DATABASE_PATH
    (default ./aftermind.db). GraphStore is still the in-process
    default — Graphiti/Neo4j is Phase 2.
    """
    db_path = os.environ.get("DATABASE_PATH", DEFAULT_DB_PATH)
    client = SqliteClient(db_path)

    return AftermindService(
        knowledge_store=SqliteKnowledgeStore(client),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=SqliteCheckpointStore(client),
        lifecycle_store=SqliteLifecycleStore(client),
        llm_provider=_LazyLLMProvider(),
        episode_store=SqliteEpisodeStore(client),
        decision_store=SqliteDecisionStore(client),
    )
