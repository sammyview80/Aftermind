from domain.models.scope import MemoryScope
from providers.graphiti.store import GraphitiStore, _scope_key


class FakeWriter:
    def __init__(self) -> None:
        self.calls = []

    def add_fact(self, source, relation, target, group_id):
        self.calls.append((source, relation, target, group_id))


class FakeClient:
    def __init__(self, records=None) -> None:
        self.records = records or []
        self.calls = []

    def run(self, query, **params):
        self.calls.append((query, params))
        return self.records


def test_upsert_entity_is_a_noop():
    # graphiti-core has no concept of a bare entity outside a
    # relationship — upsert_relationship covers both endpoints.
    writer = FakeWriter()
    GraphitiStore(writer, FakeClient()).upsert_entity("Aftermind")
    assert writer.calls == []


def test_upsert_relationship_delegates_to_the_graphiti_writer():
    writer = FakeWriter()
    scope = MemoryScope.of(tenant_id="t1")

    GraphitiStore(writer, FakeClient()).upsert_relationship("Aftermind", "USES", "PostgreSQL", scope=scope)

    assert writer.calls == [("Aftermind", "USES", "PostgreSQL", _scope_key(scope))]


def test_upsert_relationship_with_no_scope_uses_unscoped_group_id():
    writer = FakeWriter()
    GraphitiStore(writer, FakeClient()).upsert_relationship("A", "USES", "B")
    assert writer.calls == [("A", "USES", "B", "unscoped")]


def test_find_related_queries_by_exact_name_and_group_id():
    client = FakeClient(records=[{"name": "PostgreSQL"}, {"name": "Graphiti"}])
    scope = MemoryScope.of(tenant_id="t1")

    related = GraphitiStore(FakeWriter(), client).find_related("Aftermind", scope=scope, limit=3)

    assert related == ["PostgreSQL", "Graphiti"]
    query, params = client.calls[0]
    assert "RELATES_TO" in query
    assert params == {"name": "Aftermind", "group_id": _scope_key(scope), "limit": 3}


def test_find_related_with_no_scope_uses_unscoped_group_id():
    client = FakeClient(records=[])
    GraphitiStore(FakeWriter(), client).find_related("Aftermind")
    _, params = client.calls[0]
    assert params["group_id"] == "unscoped"


def test_mark_historical_sets_expired_at_on_the_matching_edge():
    client = FakeClient()
    scope = MemoryScope.of(tenant_id="t1")

    GraphitiStore(FakeWriter(), client).mark_historical("Billing", "USES", "Redis", scope=scope)

    query, params = client.calls[0]
    assert "SET rel.expired_at" in query
    assert params == {"source": "Billing", "target": "Redis", "relation": "USES", "group_id": _scope_key(scope)}


def test_find_relationships_excludes_expired_edges_in_query():
    client = FakeClient(records=[])
    GraphitiStore(FakeWriter(), client).find_relationships("Billing")
    query, _ = client.calls[0]
    assert "rel.expired_at IS NULL" in query


def test_find_historical_relationships_only_matches_expired_edges():
    client = FakeClient(records=[{"source": "Billing", "relation": "USES", "target": "Redis"}])

    relationships = GraphitiStore(FakeWriter(), client).find_historical_relationships("Billing")

    assert relationships == [("Billing", "USES", "Redis")]
    query, _ = client.calls[0]
    assert "rel.expired_at IS NOT NULL" in query


def test_scope_key_sanitizes_colons_and_asterisks_for_graphiti_group_id():
    scope = MemoryScope.of(tenant_id="t1")
    key = _scope_key(scope)
    assert ":" not in key
    assert "*" not in key
    assert key.replace("_", "").replace("-", "").isalnum()
