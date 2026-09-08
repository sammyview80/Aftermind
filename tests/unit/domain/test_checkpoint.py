from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.models.checkpoint import Checkpoint
from domain.models.scope import MemoryScope


def test_defaults_generate_id_and_created_at():
    checkpoint = Checkpoint()
    assert checkpoint.checkpoint_id
    assert isinstance(checkpoint.created_at, datetime)
    assert checkpoint.created_at.tzinfo == timezone.utc


def test_construct_with_all_fields():
    scope = MemoryScope.of(tenant_id="t1")
    checkpoint = Checkpoint(
        scope=scope,
        summary="Implemented login flow, tests passing",
        memory_ids=["m1", "m2"],
        last_experience_id="exp1",
        reason="task_completed",
        metadata={"agent": "coder"},
    )

    assert checkpoint.scope is scope
    assert checkpoint.summary == "Implemented login flow, tests passing"
    assert checkpoint.memory_ids == ("m1", "m2")
    assert checkpoint.last_experience_id == "exp1"
    assert checkpoint.reason == "task_completed"
    assert checkpoint.metadata == {"agent": "coder"}


def test_memory_ids_stored_as_tuple():
    ids = ["m1"]
    checkpoint = Checkpoint(memory_ids=ids)
    assert isinstance(checkpoint.memory_ids, tuple)
    ids.append("m2")  # mutate original list after construction
    assert checkpoint.memory_ids == ("m1",)


def test_metadata_is_immutable_mapping():
    checkpoint = Checkpoint(metadata={"k": "v"})
    assert isinstance(checkpoint.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        checkpoint.metadata["k"] = "changed"


def test_checkpoint_is_frozen():
    checkpoint = Checkpoint()
    with pytest.raises(Exception):
        checkpoint.summary = "changed"


def test_defaults_have_no_scope_or_experience_link():
    checkpoint = Checkpoint()
    assert checkpoint.scope is None
    assert checkpoint.last_experience_id is None
    assert checkpoint.memory_ids == ()
