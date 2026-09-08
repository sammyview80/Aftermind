from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.enums.memory_type import MemoryType
from domain.models.memory import Memory
from domain.models.scope import MemoryScope


def test_defaults_generate_id_version_and_timestamps():
    memory = Memory()
    assert memory.memory_id
    assert memory.version == 1
    assert isinstance(memory.created_at, datetime)
    assert isinstance(memory.updated_at, datetime)
    assert memory.created_at.tzinfo == timezone.utc


def test_construct_with_all_fields():
    scope = MemoryScope.of(tenant_id="t1")
    memory = Memory(
        scope=scope,
        content="User prefers dark mode",
        memory_type=MemoryType.SEMANTIC,
        entities=["user", "dark_mode"],
        relationships=["user prefers dark_mode"],
        confidence=0.9,
        version=2,
        superseded_by="m2",
        source_candidate_ids=["c1", "c2"],
        metadata={"tag": "preference"},
    )

    assert memory.scope is scope
    assert memory.content == "User prefers dark mode"
    assert memory.memory_type == MemoryType.SEMANTIC
    assert memory.entities == ("user", "dark_mode")
    assert memory.relationships == ("user prefers dark_mode",)
    assert memory.confidence == 0.9
    assert memory.version == 2
    assert memory.superseded_by == "m2"
    assert memory.source_candidate_ids == ("c1", "c2")
    assert memory.metadata == {"tag": "preference"}


def test_entities_relationships_and_source_candidate_ids_stored_as_tuples():
    entities = ["a"]
    memory = Memory(entities=entities, relationships=["a rel b"], source_candidate_ids=["c1"])
    assert isinstance(memory.entities, tuple)
    assert isinstance(memory.relationships, tuple)
    assert isinstance(memory.source_candidate_ids, tuple)

    entities.append("b")  # mutate original list after construction
    assert memory.entities == ("a",)


def test_metadata_is_immutable_mapping():
    memory = Memory(metadata={"k": "v"})
    assert isinstance(memory.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        memory.metadata["k"] = "changed"


def test_memory_is_frozen():
    memory = Memory()
    with pytest.raises(Exception):
        memory.content = "changed"


def test_superseded_by_defaults_to_none():
    memory = Memory()
    assert memory.superseded_by is None


@pytest.mark.parametrize(
    "memory_type",
    [MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.PROCEDURAL],
)
def test_every_memory_type_constructs(memory_type):
    memory = Memory(memory_type=memory_type)
    assert memory.memory_type == memory_type
    assert memory.memory_type == memory_type.value
