from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.enums.reconciliation_action import ReconciliationAction
from domain.models.memory_decision import MemoryDecision


def test_defaults_generate_id_and_created_at():
    decision = MemoryDecision()
    assert decision.decision_id
    assert isinstance(decision.created_at, datetime)
    assert decision.created_at.tzinfo == timezone.utc


def test_defaults_to_ignore_with_no_target():
    decision = MemoryDecision()
    assert decision.action == ReconciliationAction.IGNORE
    assert decision.target_memory_id is None
    assert decision.evidence_memory_ids == ()


def test_construct_with_all_fields():
    decision = MemoryDecision(
        candidate_id="c1",
        action=ReconciliationAction.MERGE,
        target_memory_id="m1",
        evidence_memory_ids=["m1", "m2"],
        confidence=0.85,
        reasoning="Candidate restates an existing preference with more detail.",
        metadata={"searched": "3 memories"},
    )

    assert decision.candidate_id == "c1"
    assert decision.action == ReconciliationAction.MERGE
    assert decision.target_memory_id == "m1"
    assert decision.evidence_memory_ids == ("m1", "m2")
    assert decision.confidence == 0.85
    assert decision.reasoning == "Candidate restates an existing preference with more detail."
    assert decision.metadata == {"searched": "3 memories"}


def test_evidence_memory_ids_stored_as_tuple():
    ids = ["m1"]
    decision = MemoryDecision(evidence_memory_ids=ids)
    assert isinstance(decision.evidence_memory_ids, tuple)
    ids.append("m2")  # mutate original list after construction
    assert decision.evidence_memory_ids == ("m1",)


def test_metadata_is_immutable_mapping():
    decision = MemoryDecision(metadata={"k": "v"})
    assert isinstance(decision.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        decision.metadata["k"] = "changed"


def test_decision_is_frozen():
    decision = MemoryDecision()
    with pytest.raises(Exception):
        decision.reasoning = "changed"


@pytest.mark.parametrize(
    "action",
    [
        ReconciliationAction.IGNORE,
        ReconciliationAction.CREATE,
        ReconciliationAction.UPDATE,
        ReconciliationAction.MERGE,
        ReconciliationAction.SUPERSEDE,
    ],
)
def test_every_action_constructs(action):
    decision = MemoryDecision(action=action)
    assert decision.action == action
    assert decision.action == action.value


def test_create_action_has_no_target_memory():
    decision = MemoryDecision(action=ReconciliationAction.CREATE, target_memory_id=None)
    assert decision.target_memory_id is None
