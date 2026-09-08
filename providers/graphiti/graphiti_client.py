import asyncio
import hashlib
from datetime import datetime, timezone

from providers.graphiti.client import DEFAULT_TIMEOUT_SECONDS, driver_config

EMBEDDING_DIM = 16


def _deterministic_embedding(text: str) -> list[float]:
    """A fast, dependency-free stand-in for a real embedding model —
    enough for graphiti-core's internal exact-duplicate dedup (identical
    text -> identical vector; Neo4j's vector.similarity.cosine also
    rejects an all-zero vector, so this must be non-zero and normalized).
    Not semantically meaningful — swap for a real embedder (OpenAI,
    local model) once semantic graph search is needed. Entity/
    relationship traversal (GraphitiStore.find_related) doesn't depend
    on it; that's plain Cypher by exact name.
    """
    digest = hashlib.sha256(text.encode()).digest()
    raw = [(b / 127.5) - 1.0 for b in digest[:EMBEDDING_DIM]]
    norm = sum(v * v for v in raw) ** 0.5
    return [v / norm for v in raw]


def _build_graphiti(uri: str, user: str, password: str, timeout: float = DEFAULT_TIMEOUT_SECONDS):
    """Construct a real graphiti_core.Graphiti instance — imported
    lazily so this module never requires graphiti-core/neo4j installed
    unless actually used.

    graphiti-core's own Neo4jDriver builds its async neo4j driver with
    library defaults (a minute of connection/retry waiting), so it is
    given one built with Aftermind's fail-fast timeouts instead — an
    unreachable Neo4j must surface as a quick failure the outbox can
    record and retry, not a stalled observe().

    graphiti-core's edge resolution (deduplicating/contradicting a new
    fact against existing ones once there's more than one edge in a
    group_id) makes a real LLM call — it's not just cosmetic timestamp
    inference, so a stub that raises breaks after the first write per
    scope. Reuse Aftermind's existing generic LLM config (LLM_API_KEY/
    LLM_MODEL/LLM_BASE_URL — OpenRouter by default) via graphiti-core's
    own OpenAI-protocol client, since OpenRouter is OpenAI-compatible.
    Embeddings still use a deterministic local stand-in (below) since
    OpenRouter doesn't serve an embeddings endpoint and semantic graph
    search isn't what find_related() needs — that's exact-name Cypher.
    """
    try:
        from graphiti_core import Graphiti
        from graphiti_core.cross_encoder.client import CrossEncoderClient
        from graphiti_core.driver.neo4j_driver import Neo4jDriver
        from graphiti_core.embedder.client import EmbedderClient
        from graphiti_core.llm_client import LLMConfig, OpenAIClient
        from neo4j import AsyncGraphDatabase
    except ImportError as exc:
        raise ImportError(
            "GraphitiWriter requires the 'graphiti-core' and 'neo4j' packages: "
            "pip install graphiti-core neo4j"
        ) from exc

    from providers.llm.config import get_llm_config

    class _DeterministicEmbedder(EmbedderClient):
        async def create(self, input_data) -> list[float]:
            return _deterministic_embedding(str(input_data))

        async def create_batch(self, input_data_list) -> list[list[float]]:
            return [_deterministic_embedding(str(x)) for x in input_data_list]

    class _UnusedCrossEncoder(CrossEncoderClient):
        async def rank(self, query, passages):
            return [(p, 0.0) for p in passages]

    llm_config_source = get_llm_config()
    llm_client = OpenAIClient(
        config=LLMConfig(
            api_key=llm_config_source.api_key,
            model=llm_config_source.model,
            small_model=llm_config_source.model,
            base_url=llm_config_source.base_url,
        )
    )

    graph_driver = Neo4jDriver(uri, user, password)
    default_client = graph_driver.client
    graph_driver.client = AsyncGraphDatabase.driver(uri, auth=(user or "", password or ""), **driver_config(timeout))
    # The replaced default driver never opened a connection; closing it is
    # awaited by the caller (see _add_fact_async) since this is sync code.
    graph_driver._aftermind_replaced_client = default_client  # noqa: SLF001

    return Graphiti(
        uri,
        user,
        password,
        llm_client=llm_client,
        embedder=_DeterministicEmbedder(),
        cross_encoder=_UnusedCrossEncoder(),
        graph_driver=graph_driver,
    )


class GraphitiWriter:
    """Sync-to-async bridge around graphiti-core's Graphiti for writing
    (source, relation, target) facts via the real library
    (Graphiti.add_triplet), not raw Cypher — this is Aftermind's actual
    "write with graphiti" seam. Reads (GraphitiStore.find_related) go
    through direct Cypher against the same graph instead, since
    graphiti-core's own semantic search needs a real embedding model
    this deterministic stand-in can't provide.

    A fresh Graphiti (and its underlying async Neo4j driver) is built
    and closed *within* each add_fact() call's own asyncio.run() — never
    held across calls. asyncio.run() creates a new event loop every
    time, and an async neo4j driver's connections are bound to the loop
    that created them; reusing one persistent driver across separate
    asyncio.run() calls fails with "Future attached to a different loop".
    Aftermind's write volume doesn't need a pooled long-lived driver
    here; correctness under a sync facade does.
    """

    def __init__(self, uri: str, user: str, password: str, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._timeout = timeout

    def add_fact(self, source: str, relation: str, target: str, group_id: str) -> None:
        asyncio.run(self._add_fact_async(source, relation, target, group_id))

    async def _add_fact_async(self, source: str, relation: str, target: str, group_id: str) -> None:
        from graphiti_core.edges import EntityEdge
        from graphiti_core.nodes import EntityNode

        graphiti = _build_graphiti(self._uri, self._user, self._password, timeout=self._timeout)
        replaced = getattr(graphiti.driver, "_aftermind_replaced_client", None)
        if replaced is not None:
            await replaced.close()
        try:
            embedder = graphiti.embedder
            source_node = EntityNode(name=source, group_id=group_id, labels=["Entity"])
            target_node = EntityNode(name=target, group_id=group_id, labels=["Entity"])
            source_node.name_embedding = await embedder.create(source_node.name)
            target_node.name_embedding = await embedder.create(target_node.name)

            fact = f"{source} {relation} {target}"
            edge = EntityEdge(
                source_node_uuid=source_node.uuid,
                target_node_uuid=target_node.uuid,
                name=relation,
                fact=fact,
                group_id=group_id,
                created_at=datetime.now(timezone.utc),
            )
            edge.fact_embedding = await embedder.create(fact)

            await graphiti.add_triplet(source_node, edge, target_node)
        finally:
            await graphiti.close()

    def close(self) -> None:
        pass  # nothing to close — no persistent connection is held
