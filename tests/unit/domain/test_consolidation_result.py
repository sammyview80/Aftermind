from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.models.consolidation_result import ConsolidationResult


def test_defaults_generate_id_and_created_at_and_are_not_accepted():
    result = ConsolidationResult()
    assert result.result_id
    assert result.accepted is False
    assert isinstance(result.created_at, datetime)
    assert result.created_at.tzinfo == timezone.utc


def test_construct_with_all_fields():
    result = ConsolidationResult(
        candidate_id="c1",
        accepted=True,
        document_id="doc1",
        document_slug="client-prefs",
        source_memory_ids=["m1", "m2", "m3"],
        reasoning="Accepted: clear pattern across memories.",
        metadata={"trigger": "topic_threshold"},
    )

    assert result.candidate_id == "c1"
    assert result.accepted is True
    assert result.document_id == "doc1"
    assert result.document_slug == "client-prefs"
    assert result.source_memory_ids == ("m1", "m2", "m3")
    assert result.metadata == {"trigger": "topic_threshold"}


def test_source_memory_ids_stored_as_tuple():
    ids = ["m1"]
    result = ConsolidationResult(source_memory_ids=ids)
    assert isinstance(result.source_memory_ids, tuple)
    ids.append("m2")
    assert result.source_memory_ids == ("m1",)


def test_metadata_is_immutable_mapping():
    result = ConsolidationResult(metadata={"k": "v"})
    assert isinstance(result.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        result.metadata["k"] = "changed"


def test_result_is_frozen():
    result = ConsolidationResult()
    with pytest.raises(Exception):
        result.accepted = True


def test_rejected_result_has_no_document_link():
    result = ConsolidationResult(accepted=False)
    assert result.document_id is None
    assert result.document_slug is None
