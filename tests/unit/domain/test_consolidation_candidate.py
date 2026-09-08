from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.models.consolidation_candidate import ConsolidationCandidate
from domain.models.scope import MemoryScope


def test_defaults_generate_id_and_created_at():
    candidate = ConsolidationCandidate()
    assert candidate.candidate_id
    assert isinstance(candidate.created_at, datetime)
    assert candidate.created_at.tzinfo == timezone.utc


def test_construct_with_all_fields():
    scope = MemoryScope.of(tenant_id="t1")
    candidate = ConsolidationCandidate(
        scope=scope,
        topic="client preference",
        source_memory_ids=["m1", "m2", "m3"],
        proposed_content="Client prefers premium dark visual styles.",
        confidence=0.85,
        reasoning="All three memories describe visual style preference.",
        trigger_reason="topic_threshold",
        metadata={"cluster_size": 3},
    )

    assert candidate.scope is scope
    assert candidate.topic == "client preference"
    assert candidate.source_memory_ids == ("m1", "m2", "m3")
    assert candidate.proposed_content == "Client prefers premium dark visual styles."
    assert candidate.confidence == 0.85
    assert candidate.trigger_reason == "topic_threshold"
    assert candidate.metadata == {"cluster_size": 3}


def test_source_memory_ids_stored_as_tuple():
    ids = ["m1"]
    candidate = ConsolidationCandidate(source_memory_ids=ids)
    assert isinstance(candidate.source_memory_ids, tuple)
    ids.append("m2")
    assert candidate.source_memory_ids == ("m1",)


def test_metadata_is_immutable_mapping():
    candidate = ConsolidationCandidate(metadata={"k": "v"})
    assert isinstance(candidate.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        candidate.metadata["k"] = "changed"


def test_candidate_is_frozen():
    candidate = ConsolidationCandidate()
    with pytest.raises(Exception):
        candidate.proposed_content = "changed"
