import re
from typing import Optional

from domain.models.scope import MemoryScope
from providers.graphiti.client import Neo4jClient
from providers.graphiti.graphiti_client import GraphitiWriter

_UNSAFE_GROUP_ID_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def _scope_key(scope: Optional[MemoryScope]) -> str:
    """graphiti-core's group_id only allows alphanumeric/dash/underscore
    — MemoryScope.key() uses ":" to join levels and "*" for unset ones,
    both rejected. Sanitize rather than change MemoryScope's own key
    format, which other stores (SQLite, OpenKnowledge) already rely on."""
    raw = scope.key() if scope is not None else "unscoped"
    return _UNSAFE_GROUP_ID_CHARS.sub("_", raw)


class GraphitiStore:
    """GraphStore implementation backed by real graphiti-core for writes
    and direct Cypher for reads against the same Neo4j graph.

    Entities/relationships are scoped via graphiti-core's own `group_id`
    field (mapped from MemoryScope.key()), so different tenants/projects
    don't bleed into each other's graph — matching Postgres/OpenKnowledge's
    scope isolation.
    """

    def __init__(self, writer: GraphitiWriter, client: Neo4jClient) -> None:
        self._writer = writer
        self._client = client

    def upsert_entity(self, name: str, scope: Optional[MemoryScope] = None) -> None:
        # graphiti-core creates entity nodes as part of add_triplet — a
        # bare entity with no relationship isn't a graphiti-core concept
        # on its own, so this is a no-op; upsert_relationship covers both
        # endpoints.
        pass

    def upsert_relationship(
        self, source: str, relation: str, target: str, scope: Optional[MemoryScope] = None
    ) -> None:
        self._writer.add_fact(source, relation, target, group_id=_scope_key(scope))

    def find_related(self, entity: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[str]:
        # Case-insensitive: callers (e.g. RecallPlanner's keyword
        # extraction) lowercase entity seeds, while entity names stored
        # via add_fact keep the casing they were extracted with.
        records = self._client.run(
            "MATCH (a:Entity)-[rel:RELATES_TO]->(b:Entity) "
            "WHERE toLower(a.name) = toLower($name) AND a.group_id = $group_id AND rel.expired_at IS NULL "
            "RETURN DISTINCT b.name AS name LIMIT $limit",
            name=entity,
            group_id=_scope_key(scope),
            limit=limit,
        )
        return [record["name"] for record in records]

    def find_relationships(
        self, entity: str, scope: Optional[MemoryScope] = None, limit: int = 5
    ) -> list[tuple[str, str, str]]:
        records = self._client.run(
            "MATCH (a:Entity)-[rel:RELATES_TO]->(b:Entity) "
            "WHERE toLower(a.name) = toLower($name) AND a.group_id = $group_id AND rel.expired_at IS NULL "
            "RETURN DISTINCT a.name AS source, rel.name AS relation, b.name AS target LIMIT $limit",
            name=entity,
            group_id=_scope_key(scope),
            limit=limit,
        )
        return [(record["source"], record["relation"] or "related_to", record["target"]) for record in records]

    def mark_historical(
        self, source: str, relation: str, target: str, scope: Optional[MemoryScope] = None
    ) -> None:
        self._client.run(
            "MATCH (a:Entity)-[rel:RELATES_TO]->(b:Entity) "
            "WHERE toLower(a.name) = toLower($source) AND toLower(b.name) = toLower($target) "
            "AND rel.name = $relation AND a.group_id = $group_id AND rel.expired_at IS NULL "
            "SET rel.expired_at = datetime()",
            source=source,
            target=target,
            relation=relation,
            group_id=_scope_key(scope),
        )

    def find_historical_relationships(
        self, entity: str, scope: Optional[MemoryScope] = None, limit: int = 5
    ) -> list[tuple[str, str, str]]:
        records = self._client.run(
            "MATCH (a:Entity)-[rel:RELATES_TO]->(b:Entity) "
            "WHERE toLower(a.name) = toLower($name) AND a.group_id = $group_id AND rel.expired_at IS NOT NULL "
            "RETURN DISTINCT a.name AS source, rel.name AS relation, b.name AS target LIMIT $limit",
            name=entity,
            group_id=_scope_key(scope),
            limit=limit,
        )
        return [(record["source"], record["relation"] or "related_to", record["target"]) for record in records]
