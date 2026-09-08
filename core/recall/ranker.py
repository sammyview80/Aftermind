from domain.models.memory import Memory

DEFAULT_WEIGHTS = {"relevance": 0.6, "confidence": 0.2, "recency": 0.2}


def _words(text: str) -> set[str]:
    return {w.strip(".,!?:;\"'()").lower() for w in text.split() if w.strip(".,!?:;\"'()")}


def _relevance(query_words: set[str], memory: Memory) -> float:
    memory_words = _words(memory.content)
    if not query_words or not memory_words:
        return 0.0
    return len(query_words & memory_words) / len(query_words | memory_words)


class Ranker:
    """Scores retrieved memories by relevance to the search terms,
    confidence, and recency, and returns them ranked highest-first."""

    def __init__(self, weights: dict[str, float] = DEFAULT_WEIGHTS) -> None:
        self._weights = weights

    def rank(self, search_terms: tuple[str, ...], memories: list[Memory], limit: int | None = None) -> list[Memory]:
        if not memories:
            return []

        query_words: set[str] = set()
        for term in search_terms:
            query_words |= _words(term)

        by_recency = sorted(memories, key=lambda m: m.updated_at)
        recency_rank = {m.memory_id: i / max(len(by_recency) - 1, 1) for i, m in enumerate(by_recency)}

        def score(memory: Memory) -> float:
            return (
                self._weights["relevance"] * _relevance(query_words, memory)
                + self._weights["confidence"] * memory.confidence
                + self._weights["recency"] * recency_rank[memory.memory_id]
            )

        ranked = sorted(memories, key=score, reverse=True)
        return ranked[:limit] if limit is not None else ranked
