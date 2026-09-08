from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.enums.memory_type import MemoryType
from domain.models.candidate import Candidate
from domain.models.scope import MemoryScope


def test_defaults_generate_id_and_created_at():
    candidate = Candidate()
    assert candidate.candidate_id
    assert isinstance(candidate.created_at, datetime)
    assert candidate.created_at.tzinfo == timezone.utc


def test_construct_with_all_fields():
    scope = MemoryScope.of(tenant_id="t1")
    candidate = Candidate(
        experience_id="exp1",
        scope=scope,
        content="User prefers dark mode",
        memory_type=MemoryType.SEMANTIC,
        entities=["user", "dark_mode"],
        relationships=["user prefers dark_mode"],
        confidence=0.9,
        future_usefulness=0.8,
        durability=0.7,
        novelty=0.6,
        impact=0.5,
        specificity=0.4,
        user_confirmed=True,
        source_event_ids=["e1", "e2"],
        metadata={"tag": "preference"},
    )

    assert candidate.experience_id == "exp1"
    assert candidate.scope is scope
    assert candidate.content == "User prefers dark mode"
    assert candidate.memory_type == MemoryType.SEMANTIC
    assert candidate.entities == ("user", "dark_mode")
    assert candidate.relationships == ("user prefers dark_mode",)
    assert candidate.confidence == 0.9
    assert candidate.future_usefulness == 0.8
    assert candidate.durability == 0.7
    assert candidate.novelty == 0.6
    assert candidate.impact == 0.5
    assert candidate.specificity == 0.4
    assert candidate.user_confirmed is True
    assert candidate.source_event_ids == ("e1", "e2")
    assert candidate.metadata == {"tag": "preference"}


def test_score_fields_default_to_zero():
    candidate = Candidate()
    assert candidate.confidence == 0.0
    assert candidate.future_usefulness == 0.0
    assert candidate.durability == 0.0
    assert candidate.novelty == 0.0
    assert candidate.impact == 0.0
    assert candidate.specificity == 0.0


def test_user_confirmed_defaults_to_none():
    candidate = Candidate()
    assert candidate.user_confirmed is None


def test_entities_relationships_and_source_event_ids_stored_as_tuples():
    entities = ["a", "b"]
    relationships = ["a rel b"]
    source_event_ids = ["e1"]
    candidate = Candidate(
        entities=entities,
        relationships=relationships,
        source_event_ids=source_event_ids,
    )
    assert isinstance(candidate.entities, tuple)
    assert isinstance(candidate.relationships, tuple)
    assert isinstance(candidate.source_event_ids, tuple)

    entities.append("c")  # mutate original list after construction
    assert candidate.entities == ("a", "b")


def test_metadata_is_immutable_mapping():
    candidate = Candidate(metadata={"k": "v"})
    assert isinstance(candidate.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        candidate.metadata["k"] = "changed"


def test_candidate_is_frozen():
    candidate = Candidate()
    with pytest.raises(Exception):
        candidate.content = "changed"


@pytest.mark.parametrize(
    "memory_type",
    [MemoryType.SEMANTIC, MemoryType.EPISODIC, MemoryType.PROCEDURAL],
)
def test_every_memory_type_constructs(memory_type):
    candidate = Candidate(memory_type=memory_type)
    assert candidate.memory_type == memory_type
    assert candidate.memory_type == memory_type.value


def test_defaults_have_no_experience_or_scope_link():
    candidate = Candidate()
    assert candidate.experience_id is None
    assert candidate.scope is None
    assert candidate.entities == ()
    assert candidate.relationships == ()
    assert candidate.source_event_ids == ()
