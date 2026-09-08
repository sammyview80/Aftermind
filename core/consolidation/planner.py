from dataclasses import dataclass, field
from typing import Optional

from core.consolidation.triggers import DEFAULT_MEMORY_COUNT_THRESHOLD, ConsolidationTrigger
from domain.models.memory import Memory
from domain.models.scope import MemoryScope

DEFAULT_SIMILARITY_THRESHOLD = 0.2
_STOPWORDS = frozenset(
    {"the", "a", "an", "and", "or", "but", "for", "with", "this", "that", "is", "are", "was", "were", "to", "of"}
)


@dataclass(frozen=True)
class ConsolidationPlan:
    """A cluster of related memories worth consolidating, plus why. An
    intermediate value — not persisted — that the consolidator turns
    into a ConsolidationCandidate."""

    scope: Optional[MemoryScope]
    topic: str
    memories: tuple[Memory, ...] = field(default_factory=tuple)
    trigger: ConsolidationTrigger = ConsolidationTrigger.MANUAL


def _words(text: str) -> set[str]:
    return {w.strip(".,!?").lower() for w in text.split() if len(w.strip(".,!?")) > 2 and w.lower() not in _STOPWORDS}


def _similarity(a: set[str], b: set[str]) -> float:
    """Overlap relative to the smaller set, not full Jaccard — short
    sentences that share one strong subject word (e.g. "client") but
    little else should still cluster together."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _label(memories: list[Memory]) -> str:
    counts: dict[str, int] = {}
    for memory in memories:
        for word in _words(memory.content):
            counts[word] = counts.get(word, 0) + 1
    if not counts:
        return memories[0].content[:40]
    top = max(counts.items(), key=lambda pair: (pair[1], pair[0]))
    return top[0]


class ConsolidationPlanner:
    """Groups related memories into clusters worth consolidating.

    Clustering here is a simple word-overlap heuristic (consistent with
    the rest of the codebase's fake/dev-friendly retrieval logic) — a
    real deployment can swap this for embedding-based clustering behind
    the same `plan()` signature.
    """

    def __init__(
        self,
        min_group_size: int = DEFAULT_MEMORY_COUNT_THRESHOLD,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        self.min_group_size = min_group_size
        self.similarity_threshold = similarity_threshold

    def plan(
        self,
        memories: list[Memory],
        trigger: ConsolidationTrigger,
        scope: Optional[MemoryScope] = None,
    ) -> list[ConsolidationPlan]:
        clusters = self._cluster(memories)
        return [
            ConsolidationPlan(scope=scope, topic=_label(cluster), memories=tuple(cluster), trigger=trigger)
            for cluster in clusters
            if len(cluster) >= self.min_group_size
        ]

    def _cluster(self, memories: list[Memory]) -> list[list[Memory]]:
        # Complete-linkage: a memory joins a group only if it's similar
        # enough to EVERY member already in it, not just one. Single-
        # linkage would let one weak, generic shared word (e.g. "prefers")
        # transitively chain two otherwise-unrelated topics into one
        # cluster.
        word_sets = [_words(m.content) for m in memories]
        groups: list[list[int]] = []

        for i in range(len(memories)):
            placed = False
            for group in groups:
                if all(_similarity(word_sets[i], word_sets[j]) >= self.similarity_threshold for j in group):
                    group.append(i)
                    placed = True
                    break
            if not placed:
                groups.append([i])

        return [[memories[i] for i in group] for group in groups]
