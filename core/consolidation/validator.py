from domain.models.consolidation_candidate import ConsolidationCandidate
from domain.models.consolidation_result import ConsolidationResult

DEFAULT_MIN_CONFIDENCE = 0.4
DEFAULT_MIN_SOURCE_MEMORIES = 2


class ConsolidationValidator:
    """Sanity-checks a ConsolidationCandidate before it's written to
    OpenKnowledge — guards against the LLM proposing something too
    thin, too uncertain, or that lost provenance, rather than trusting
    the model's output as-is."""

    def __init__(
        self,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
        min_source_memories: int = DEFAULT_MIN_SOURCE_MEMORIES,
    ) -> None:
        self.min_confidence = min_confidence
        self.min_source_memories = min_source_memories

    def validate(self, candidate: ConsolidationCandidate) -> ConsolidationResult:
        reason = self._rejection_reason(candidate)
        if reason:
            return ConsolidationResult(
                candidate_id=candidate.candidate_id,
                accepted=False,
                source_memory_ids=candidate.source_memory_ids,
                reasoning=reason,
            )
        return ConsolidationResult(
            candidate_id=candidate.candidate_id,
            accepted=True,
            source_memory_ids=candidate.source_memory_ids,
            reasoning=candidate.reasoning,
        )

    def _rejection_reason(self, candidate: ConsolidationCandidate) -> str:
        if not candidate.proposed_content.strip():
            return "rejected: empty proposed content"
        if candidate.confidence < self.min_confidence:
            return f"rejected: confidence {candidate.confidence} below threshold {self.min_confidence}"
        if len(candidate.source_memory_ids) < self.min_source_memories:
            return (
                f"rejected: only {len(candidate.source_memory_ids)} source memories, "
                f"need at least {self.min_source_memories} to preserve meaningful provenance"
            )
        return ""
