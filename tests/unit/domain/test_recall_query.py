from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.enums.memory_type import MemoryType
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope


def test_defaults_generate_id_limit_and_created_at():
    query = RecallQuery()
    assert query.query_id
    assert query.limit == 10
    assert isinstance(query.created_at, datetime)
    assert query.created_at.tzinfo == timezone.utc


def test_construct_with_all_fields():
    scope = MemoryScope.of(tenant_id="t1")
    query = RecallQuery(
        scope=scope,
        text="Continue Aftermind",
        memory_types=[MemoryType.EPISODIC, MemoryType.SEMANTIC],
        limit=5,
        metadata={"source": "cli"},
    )

    assert query.scope is scope
    assert query.text == "Continue Aftermind"
    assert query.memory_types == (MemoryType.EPISODIC, MemoryType.SEMANTIC)
    assert query.limit == 5
    assert query.metadata == {"source": "cli"}


def test_memory_types_stored_as_tuple():
    types = [MemoryType.SEMANTIC]
    query = RecallQuery(memory_types=types)
    assert isinstance(query.memory_types, tuple)
    types.append(MemoryType.EPISODIC)  # mutate original list after construction
    assert query.memory_types == (MemoryType.SEMANTIC,)


def test_metadata_is_immutable_mapping():
    query = RecallQuery(metadata={"k": "v"})
    assert isinstance(query.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        query.metadata["k"] = "changed"


def test_recall_query_is_frozen():
    query = RecallQuery()
    with pytest.raises(Exception):
        query.text = "changed"


def test_defaults_have_no_scope_or_memory_type_filter():
    query = RecallQuery()
    assert query.scope is None
    assert query.memory_types == ()
