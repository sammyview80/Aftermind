import re
from typing import Optional

from domain.models.scope import MemoryScope
from providers.graphiti.client import Neo4jClient

_UNSAFE_RELATION_CHARS = re.compile(r"[^A-Z0-9_]")


def _scope_key(scope: Optional[MemoryScope]) -> str:
    return scope.key() if scope is not None else "*"


def _safe_relation_type(relation: str) -> str:
    """Cypher relationship types can't be parameterized — they're
    interpolated into the query string — so sanitize to [A-Z0-9_] only
    and guarantee a valid label, rather than trust caller input."""
    cleaned = re.sub(r"_+", "_", _UNSAFE_RELATION_CHARS.sub("_", relation.upper())).strip("_")
    if not cleaned:
        cleaned = "RELATED_TO"
    if cleaned[0].isdigit():
        cleaned = f"REL_{cleaned}"
    return cleaned


class GraphitiStore:
    """GraphStore implementation backed by Neo4jClient. Entities/
    relationships are scoped (MemoryScope.key()) so different
    tenants/projects don't bleed into each other's graph."""

    def __init__(self, client: Neo4jClient) -> None:
        self._client = client

    def upsert_entity(self, name: str, scope: Optional[MemoryScope] = None) -> None:
        self._client.run(
            "MERGE (e:Entity {name: $name, scope: $scope})",
            name=name,
            scope=_scope_key(scope),
        )

    def upsert_relationship(
        self, source: str, relation: str, target: str, scope: Optional[MemoryScope] = None
    ) -> None:
        relation_type = _safe_relation_type(relation)
        self._client.run(
            f"MERGE (a:Entity {{name: $source, scope: $scope}}) "
            f"MERGE (b:Entity {{name: $target, scope: $scope}}) "
            f"MERGE (a)-[:{relation_type}]->(b)",
            source=source,
            target=target,
            scope=_scope_key(scope),
        )

    def find_related(self, entity: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[str]:
        records = self._client.run(
            "MATCH (a:Entity {name: $name, scope: $scope})-[]->(b:Entity) "
            "RETURN DISTINCT b.name AS name LIMIT $limit",
            name=entity,
            scope=_scope_key(scope),
            limit=limit,
        )
        return [record["name"] for record in records]
