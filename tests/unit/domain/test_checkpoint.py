from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.models.checkpoint import Checkpoint
from domain.models.scope import MemoryScope


def test_defaults_generate_id_version_and_created_at():
    checkpoint = Checkpoint()
    assert checkpoint.checkpoint_id
    assert checkpoint.version == 1
    assert isinstance(checkpoint.created_at, datetime)
    assert checkpoint.created_at.tzinfo == timezone.utc


def test_construct_with_all_fields():
    scope = MemoryScope.of(tenant_id="t1")
    checkpoint = Checkpoint(
        scope=scope,
        version=2,
        goal="Build the login flow",
        completed=["searched repo", "found auth module"],
        current="wiring up session handling",
        blockers=["waiting on OAuth client secret"],
        next_steps=["add tests", "wire up refresh tokens"],
        memory_ids=["m1", "m2"],
        last_experience_id="exp1",
        reason="task_completed",
        metadata={"agent": "coder"},
    )

    assert checkpoint.scope is scope
    assert checkpoint.version == 2
    assert checkpoint.goal == "Build the login flow"
    assert checkpoint.completed == ("searched repo", "found auth module")
    assert checkpoint.current == "wiring up session handling"
    assert checkpoint.blockers == ("waiting on OAuth client secret",)
    assert checkpoint.next_steps == ("add tests", "wire up refresh tokens")
    assert checkpoint.memory_ids == ("m1", "m2")
    assert checkpoint.last_experience_id == "exp1"
    assert checkpoint.reason == "task_completed"
    assert checkpoint.metadata == {"agent": "coder"}


def test_list_fields_stored_as_tuples():
    completed = ["step1"]
    checkpoint = Checkpoint(completed=completed)
    assert isinstance(checkpoint.completed, tuple)
    completed.append("step2")  # mutate original list after construction
    assert checkpoint.completed == ("step1",)


def test_metadata_is_immutable_mapping():
    checkpoint = Checkpoint(metadata={"k": "v"})
    assert isinstance(checkpoint.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        checkpoint.metadata["k"] = "changed"


def test_checkpoint_is_frozen():
    checkpoint = Checkpoint()
    with pytest.raises(Exception):
        checkpoint.current = "changed"


def test_defaults_have_no_scope_or_experience_link():
    checkpoint = Checkpoint()
    assert checkpoint.scope is None
    assert checkpoint.last_experience_id is None
    assert checkpoint.memory_ids == ()
    assert checkpoint.completed == ()
    assert checkpoint.blockers == ()
    assert checkpoint.next_steps == ()
