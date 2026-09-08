from functools import lru_cache

from core.facade import AftermindService
from providers.inmemory.store import (
    InMemoryCheckpointStore,
    InMemoryGraphStore,
    InMemoryKnowledgeStore,
    InMemoryLifecycleStore,
)
from providers.llm.openrouter import OpenRouterProvider


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
    use. In-memory stores by default (see providers/inmemory/store.py) —
    swap for Postgres/Neo4j/OpenKnowledge-backed ones for production
    persistence.
    """
    return AftermindService(
        knowledge_store=InMemoryKnowledgeStore(),
        graph_store=InMemoryGraphStore(),
        checkpoint_store=InMemoryCheckpointStore(),
        lifecycle_store=InMemoryLifecycleStore(),
        llm_provider=_LazyLLMProvider(),
    )
