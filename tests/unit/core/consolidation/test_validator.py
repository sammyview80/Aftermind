from core.consolidation.validator import ConsolidationValidator
from domain.models.consolidation_candidate import ConsolidationCandidate


def test_valid_candidate_is_accepted():
    candidate = ConsolidationCandidate(
        proposed_content="Client prefers premium dark visual styles, especially black and gold.",
        confidence=0.85,
        source_memory_ids=("m1", "m2", "m3"),
    )

    result = ConsolidationValidator().validate(candidate)

    assert result.accepted is True
    assert result.source_memory_ids == ("m1", "m2", "m3")


def test_empty_content_is_rejected():
    candidate = ConsolidationCandidate(proposed_content="   ", confidence=0.9, source_memory_ids=("m1", "m2"))
    result = ConsolidationValidator().validate(candidate)
    assert result.accepted is False
    assert "empty" in result.reasoning


def test_low_confidence_is_rejected():
    candidate = ConsolidationCandidate(proposed_content="x", confidence=0.1, source_memory_ids=("m1", "m2"))
    result = ConsolidationValidator(min_confidence=0.4).validate(candidate)
    assert result.accepted is False
    assert "confidence" in result.reasoning


def test_too_few_source_memories_is_rejected():
    candidate = ConsolidationCandidate(proposed_content="x", confidence=0.9, source_memory_ids=("m1",))
    result = ConsolidationValidator(min_source_memories=2).validate(candidate)
    assert result.accepted is False
    assert "provenance" in result.reasoning


def test_candidate_id_carries_through_to_result():
    candidate = ConsolidationCandidate(proposed_content="x", confidence=0.9, source_memory_ids=("m1", "m2"))
    result = ConsolidationValidator().validate(candidate)
    assert result.candidate_id == candidate.candidate_id
