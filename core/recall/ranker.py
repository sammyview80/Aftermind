from typing import Optional

from domain.enums.memory_status import MemoryStatus
from domain.models.memory import Memory
from domain.models.scope import MemoryScope

DEFAULT_WEIGHTS = {
    "relevance": 0.4,
    "confidence": 0.15,
    "recency": 0.15,
    "status": 0.15,
    "scope_closeness": 0.15,
}

_STATUS_WEIGHT = {
    MemoryStatus.ACTIVE: 1.0,
    MemoryStatus.DECAYED: 0.5,
    MemoryStatus.ARCHIVED: 0.1,
    MemoryStatus.EXPIRED: 0.0,
    MemoryStatus.FORGOTTEN: 0.0,
}


def _words(text: str) -> set[str]:
    return {w.strip(".,!?:;\"'()").lower() for w in text.split() if w.strip(".,!?:;\"'()")}


def _relevance(query_words: set[str], memory: Memory) -> float:
    memory_words = _words(memory.content)
    if not query_words or not memory_words:
        return 0.0
    return len(query_words & memory_words) / len(query_words | memory_words)


def _scope_closeness(query_scope: Optional[MemoryScope], memory_scope: Optional[MemoryScope]) -> float:
    """Fraction of the query scope's levels that this memory's scope
    matches exactly — 1.0 with no query scope to compare against (don't
    penalize when closeness isn't knowable), 0.0 if the memory has no
    scope at all while the query does."""
    if query_scope is None or not query_scope.levels:
        return 1.0
    if memory_scope is None:
        return 0.0
    matches = sum(1 for level, value in query_scope.levels.items() if memory_scope.get(level) == value)
    return matches / len(query_scope.levels)


class Ranker:
    """Scores retrieved memories by relevance to the search terms,
    confidence, recency, lifecycle status, and scope closeness, and
    returns them ranked highest-first — the fusion step that turns
    heterogeneous evidence from hybrid retrieval into one ordering."""

    def __init__(self, weights: dict[str, float] = DEFAULT_WEIGHTS) -> None:
        self._weights = weights

    def rank(
        self,
        search_terms: tuple[str, ...],
        memories: list[Memory],
        limit: int | None = None,
        query_scope: Optional[MemoryScope] = None,
        statuses: Optional[dict[str, MemoryStatus]] = None,
    ) -> list[Memory]:
        if not memories:
            return []

        query_words: set[str] = set()
        for term in search_terms:
            query_words |= _words(term)

        by_recency = sorted(memories, key=lambda m: m.updated_at)
        recency_rank = {m.memory_id: i / max(len(by_recency) - 1, 1) for i, m in enumerate(by_recency)}
        statuses = statuses or {}

        def score(memory: Memory) -> float:
            status = statuses.get(memory.memory_id, MemoryStatus.ACTIVE)
            return (
                self._weights["relevance"] * _relevance(query_words, memory)
                + self._weights["confidence"] * memory.confidence
                + self._weights["recency"] * recency_rank[memory.memory_id]
                + self._weights.get("status", 0.0) * _STATUS_WEIGHT.get(status, 1.0)
                + self._weights.get("scope_closeness", 0.0) * _scope_closeness(query_scope, memory.scope)
            )

        ranked = sorted(memories, key=score, reverse=True)
        return ranked[:limit] if limit is not None else ranked
