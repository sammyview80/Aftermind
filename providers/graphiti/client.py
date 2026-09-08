from typing import Any, Optional

DEFAULT_URI = "bolt://localhost:7687"


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
    ) -> None:
        if driver is not None:
            self._driver = driver
        else:
            try:
                from neo4j import GraphDatabase
            except ImportError as exc:
                raise ImportError("Neo4jClient requires the 'neo4j' package: pip install neo4j") from exc
            auth = (user, password) if user else None
            self._driver = GraphDatabase.driver(uri or DEFAULT_URI, auth=auth)

    def run(self, query: str, **params: Any) -> list:
        with self._driver.session() as session:
            return list(session.run(query, **params))

    def close(self) -> None:
        self._driver.close()
