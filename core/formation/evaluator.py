from dataclasses import replace

from domain.models.candidate import Candidate

# Words that mark a statement as tied to a fleeting moment rather than
# durable fact/preference/procedure.
_TRANSIENT_MARKERS = ("today", "right now", "currently just", "for now", "at the moment")

DEFAULT_WORTH_REMEMBERING_THRESHOLD = 0.5


class MemoryEvaluator:
    """Scores a Candidate on the dimensions that matter for durable
    memory, and decides whether it clears the bar to proceed to
    reconciliation.

    Scoring here is evidence-independent — it only looks at the candidate
    itself. Whether the candidate duplicates, updates, or contradicts an
    existing memory is decided later, by the reconciler, once evidence has
    been retrieved.
    """

    def __init__(self, threshold: float = DEFAULT_WORTH_REMEMBERING_THRESHOLD) -> None:
        self.threshold = threshold

    def evaluate(self, candidate: Candidate) -> Candidate:
        """Return a copy of `candidate` with scoring fields filled in
        (existing non-zero scores are respected, not overwritten)."""
        content = candidate.content
        word_count = len(content.split())
        is_transient = any(marker in content.lower() for marker in _TRANSIENT_MARKERS)

        return replace(
            candidate,
            confidence=candidate.confidence or 0.8,
            future_usefulness=candidate.future_usefulness or 0.7,
            durability=candidate.durability or (0.3 if is_transient else 0.7),
            novelty=candidate.novelty or 0.6,
            impact=candidate.impact or 0.6,
            specificity=candidate.specificity or (0.8 if word_count > 6 else 0.4),
        )

    def overall_score(self, candidate: Candidate) -> float:
        dimensions = (
            candidate.confidence,
            candidate.future_usefulness,
            candidate.durability,
            candidate.novelty,
            candidate.impact,
            candidate.specificity,
        )
        return sum(dimensions) / len(dimensions)

    def is_worth_remembering(self, candidate: Candidate) -> bool:
        return self.overall_score(candidate) >= self.threshold
