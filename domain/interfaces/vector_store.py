from typing import Optional, Protocol

from domain.models.scope import MemoryScope


class VectorStore(Protocol):
    """Durable embedding index for semantic recall — a companion to
    KnowledgeStore, not a replacement: content stays canonical in
    `memories`, this only maps memory_id -> embedding for similarity
    search."""

    def upsert(self, memory_id: str, scope: Optional[MemoryScope], embedding: tuple[float, ...], model: str) -> None: ...

    def search_similar(
        self, scope: Optional[MemoryScope], query_embedding: tuple[float, ...], limit: int = 5
    ) -> list[tuple[str, float]]:
        """Returns (memory_id, cosine_similarity) pairs, most similar first."""
        ...

    def delete(self, memory_id: str) -> None: ...
