import logging
from functools import lru_cache

from apps.api.settings import Settings
from core.facade import AftermindService
from core.observability import trace
from core.observability.logging_setup import configure_logging
from core.sync.worker import SyncWorker
from providers.inmemory.store import InMemoryGraphStore
from providers.llm.factory import build_llm_provider
from providers.sqlite.checkpoint_store import SqliteCheckpointStore
from providers.sqlite.client import SqliteClient
from providers.sqlite.decision_store import SqliteDecisionStore
from providers.sqlite.episode_store import SqliteEpisodeStore
from providers.sqlite.knowledge_store import SqliteKnowledgeStore
from providers.sqlite.lifecycle_store import SqliteLifecycleStore
from providers.embeddings.sentence_transformer import SentenceTransformerEmbedder
from providers.sqlite.preference_evidence_store import SqlitePreferenceEvidenceStore
from providers.sqlite.preference_store import SqlitePreferenceStore
from providers.sqlite.sync_job_store import SqliteSyncJobStore
from providers.sqlite.vector_store import SqliteVectorStore

_LOG = logging.getLogger("aftermind.api")


class _LazyLLMProvider:
    """Defers provider construction (and its credential validation) until
    the first `.complete()` call, so routes that never touch the LLM
    (health, recall, checkpoint, search) don't require credentials.
    Which provider is built follows LLM_PROVIDER (providers/llm/factory.py):
    an OpenAI-compatible key, the Codex CLI login, or the Claude Code login."""

    def __init__(self) -> None:
        self._provider = None

    def complete(self, prompt: str) -> str:
        if self._provider is None:
            self._provider = build_llm_provider()
        return self._provider.complete(prompt)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings.from_env()
    configure_logging(settings.log_level, settings.log_format)
    return settings


@lru_cache(maxsize=1)
def get_trace_sink() -> trace.InMemoryTraceSink:
    """The process's recent-trace ring buffer, exposed via /traces. It is
    attached to the default tracer so facade traces land in it as well
    as in the structured log."""
    sink = trace.InMemoryTraceSink(maxlen=get_settings().trace_buffer_size)
    trace.default_tracer.sinks.append(sink)
    return sink


@lru_cache(maxsize=1)
def get_sqlite_client() -> SqliteClient:
    return SqliteClient(get_settings().database_path)


def _build_graph_store(settings: Settings):
    """Durable backend: real graphiti-core writes + Cypher reads against
    Neo4j (NEO4J_URI/NEO4J_USER/NEO4J_PASSWORD). Falls back to the
    in-process InMemoryGraphStore — logging why — if graphiti-core/neo4j
    aren't installed or no password is configured, so the rest of the
    service still starts. A configured-but-unreachable Neo4j is *not* a
    reason to fall back: writes then fail into the durable outbox and
    are retried once it is back."""
    if not settings.neo4j_password:
        _LOG.warning("NEO4J_PASSWORD not set — GraphStore falling back to in-memory (graph state is not durable).")
        return InMemoryGraphStore()

    try:
        from providers.graphiti.client import Neo4jClient
        from providers.graphiti.graphiti_client import GraphitiWriter
        from providers.graphiti.store import GraphitiStore

        timeout = settings.neo4j_timeout_seconds
        writer = GraphitiWriter(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password, timeout=timeout)
        client = Neo4jClient(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
            timeout=timeout,
            query_timeout=settings.neo4j_query_timeout_seconds,
        )
        return GraphitiStore(writer, client)
    except ImportError as exc:
        _LOG.warning("GraphStore falling back to in-memory: %s", exc)
        return InMemoryGraphStore()


@lru_cache(maxsize=1)
def get_document_store():
    """OpenKnowledge for consolidated, human-readable knowledge (the
    Consolidation Engine's output — not every StoredMemory).
    OPENKNOWLEDGE_URL points at a running `ok start` / OK Desktop server;
    unset falls back to a local markdown directory."""
    from providers.openknowledge.store import OpenKnowledgeStore

    settings = get_settings()
    if settings.openknowledge_url:
        from providers.openknowledge.remote_client import RemoteOpenKnowledgeClient

        return OpenKnowledgeStore(RemoteOpenKnowledgeClient(settings.openknowledge_url))

    from providers.openknowledge.client import LocalMarkdownClient

    return OpenKnowledgeStore(LocalMarkdownClient())


@lru_cache(maxsize=1)
def get_service() -> AftermindService:
    """The process-wide AftermindService singleton, built once on first
    use. SQLite is the canonical store (memories, checkpoints,
    lifecycle, decisions, experiences, sync-job outbox); Neo4j/Graphiti
    and OpenKnowledge are secondary stores kept in sync through the
    durable outbox so their outages never lose a memory."""
    settings = get_settings()
    get_trace_sink()
    client = get_sqlite_client()

    return AftermindService(
        knowledge_store=SqliteKnowledgeStore(client),
        graph_store=_build_graph_store(settings),
        checkpoint_store=SqliteCheckpointStore(client),
        lifecycle_store=SqliteLifecycleStore(client),
        llm_provider=_LazyLLMProvider(),
        preference_store=SqlitePreferenceStore(client),
        preference_evidence_store=SqlitePreferenceEvidenceStore(client),
        embedder=SentenceTransformerEmbedder(settings.embedding_model) if settings.semantic_search_enabled else None,
        vector_store=SqliteVectorStore(client) if settings.semantic_search_enabled else None,
        episode_store=SqliteEpisodeStore(client),
        decision_store=SqliteDecisionStore(client),
        document_store=get_document_store(),
        sync_job_store=SqliteSyncJobStore(client),
        unit_of_work=client,
        sync_mode=settings.sync_mode,
        sync_max_attempts=settings.sync_max_attempts,
        sync_eager_timeout=settings.sync_eager_timeout_seconds,
        admission_mode=settings.effective_admission_mode,
        memory_min_score=settings.memory_min_score,
        max_candidate_chars=settings.max_candidate_chars,
    )


@lru_cache(maxsize=1)
def get_sync_worker() -> SyncWorker:
    """The background worker draining the outbox — retries failed
    graph/document syncs and resumes anything left pending by a crash."""
    settings = get_settings()
    return SyncWorker(
        job_store=SqliteSyncJobStore(get_sqlite_client()),
        dispatcher=get_service().sync,
        poll_interval=settings.sync_poll_seconds,
        batch_size=settings.sync_batch_size,
        stale_running_seconds=settings.sync_stale_running_seconds,
    )
