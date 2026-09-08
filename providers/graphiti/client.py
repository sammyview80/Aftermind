from typing import Any, Optional

DEFAULT_URI = "bolt://localhost:7687"
# Bound how long a graph read/write can hang when Neo4j is unreachable.
# The neo4j driver's defaults (60s connection acquisition, 30s
# transaction retry) would otherwise stall observe()/recall() for a
# minute before the outbox gets to record the failure and move on.
DEFAULT_TIMEOUT_SECONDS = 5.0


def driver_config(timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict[str, float]:
    """neo4j.GraphDatabase.driver keyword config that makes an outage
    fail fast (used by both the sync read client and graphiti's async
    write driver so they behave the same)."""
    return {
        "connection_timeout": timeout,
        "connection_acquisition_timeout": timeout,
        "max_transaction_retry_time": timeout,
    }


class Neo4jClient:
    """Thin wrapper around the `neo4j` driver — the single seam between
    Aftermind's graph memory (GraphStore/GraphitiStore) and the database.

    Named for providers/graphiti/ because this is where a real
    graphiti-core integration (temporal graph reasoning, episode
    ingestion) would plug in later; for now it talks directly to Neo4j
    via plain Cypher, which is enough for entity/relationship upsert and
    traversal. The `neo4j` package is imported lazily so importing this
    module never requires it installed — only instantiating this class
    without an injected driver does.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        driver=None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if driver is not None:
            self._driver = driver
        else:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:
                raise ImportError("Neo4jClient requires the 'neo4j' package: pip install neo4j") from exc
            auth = (user, password) if user else None
            self._driver = GraphDatabase.driver(uri or DEFAULT_URI, auth=auth, **driver_config(timeout))

    def run(self, query: str, **params: Any) -> list:
        with self._driver.session() as session:
            return list(session.run(query, **params))

    def close(self) -> None:
        self._driver.close()
