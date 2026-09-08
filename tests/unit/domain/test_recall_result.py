from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.models.checkpoint import Checkpoint
from domain.models.memory import Memory
from domain.models.recall_result import RecallResult


def test_defaults_generate_id_and_created_at():
    result = RecallResult()
    assert result.result_id
    assert isinstance(result.created_at, datetime)
    assert result.created_at.tzinfo == timezone.utc


def test_construct_with_all_fields():
    checkpoint = Checkpoint(goal="Build login flow")
    memories = [Memory(content="User prefers dark mode")]
    result = RecallResult(
        query_id="q1",
        checkpoint=checkpoint,
        memories=memories,
        related_entities=["login_flow", "auth_module"],
        context="## Where you left off\nGoal: Build login flow",
        metadata={"plan": "checkpoint+semantic"},
    )

    assert result.query_id == "q1"
    assert result.checkpoint is checkpoint
    assert result.memories == tuple(memories)
    assert result.related_entities == ("login_flow", "auth_module")
    assert result.context == "## Where you left off\nGoal: Build login flow"
    assert result.metadata == {"plan": "checkpoint+semantic"}


def test_memories_and_related_entities_stored_as_tuples():
    memories = [Memory()]
    entities = ["a"]
    result = RecallResult(memories=memories, related_entities=entities)
    assert isinstance(result.memories, tuple)
    assert isinstance(result.related_entities, tuple)
    memories.append(Memory())  # mutate original list after construction
    assert len(result.memories) == 1


def test_metadata_is_immutable_mapping():
    result = RecallResult(metadata={"k": "v"})
    assert isinstance(result.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        result.metadata["k"] = "changed"


def test_recall_result_is_frozen():
    result = RecallResult()
    with pytest.raises(Exception):
        result.context = "changed"


def test_defaults_have_no_checkpoint_or_memories():
    result = RecallResult()
    assert result.checkpoint is None
    assert result.memories == ()
    assert result.related_entities == ()
    assert result.context == ""
