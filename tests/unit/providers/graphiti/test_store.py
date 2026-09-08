from domain.models.scope import MemoryScope
from providers.graphiti.store import GraphitiStore, _safe_relation_type


class FakeClient:
    def __init__(self, records=None) -> None:
        self.records = records or []
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        return self.records


def test_upsert_entity_merges_by_name_and_scope():
    client = FakeClient()
    scope = MemoryScope.of(tenant_id="t1")
    GraphitiStore(client).upsert_entity("Aftermind", scope=scope)

    query, params = client.calls[0]
    assert "MERGE (e:Entity" in query
    assert params == {"name": "Aftermind", "scope": scope.key()}


def test_upsert_entity_with_no_scope_uses_wildcard():
    client = FakeClient()
    GraphitiStore(client).upsert_entity("Aftermind")

    _, params = client.calls[0]
    assert params["scope"] == "*"


def test_upsert_relationship_builds_merge_query_with_relation_type_inlined():
    client = FakeClient()
    scope = MemoryScope.of(tenant_id="t1")
    GraphitiStore(client).upsert_relationship("Aftermind", "USES", "PostgreSQL", scope=scope)

    query, params = client.calls[0]
    assert "MERGE (a:Entity {name: $source" in query
    assert "MERGE (b:Entity {name: $target" in query
    assert "[:USES]" in query
    assert params == {"source": "Aftermind", "target": "PostgreSQL", "scope": scope.key()}


def test_upsert_relationship_sanitizes_unsafe_relation_type():
    client = FakeClient()
    GraphitiStore(client).upsert_relationship("A", "runs on; DROP DATABASE", "B")

    query, _ = client.calls[0]
    assert "DROP" not in query or "[:RUNS_ON_DROP_DATABASE]" in query
    assert ";" not in query


def test_find_related_returns_names_from_records():
    client = FakeClient(records=[{"name": "PostgreSQL"}, {"name": "Graphiti"}])
    related = GraphitiStore(client).find_related("Aftermind", limit=3)

    assert related == ["PostgreSQL", "Graphiti"]
    _, params = client.calls[0]
    assert params == {"name": "Aftermind", "scope": "*", "limit": 3}


def test_safe_relation_type_strips_unsafe_characters():
    assert _safe_relation_type("uses; DROP TABLE") == "USES_DROP_TABLE"


def test_safe_relation_type_empty_falls_back_to_related_to():
    assert _safe_relation_type("!!!") == "RELATED_TO"


def test_safe_relation_type_leading_digit_gets_prefixed():
    assert _safe_relation_type("123abc") == "REL_123ABC"
