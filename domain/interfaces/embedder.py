from typing import Protocol


class Embedder(Protocol):
    """Turns text into a fixed-size embedding vector for semantic
    recall. Implementations should be deterministic for the same input
    (same model, same text -> same vector) so re-embedding on read isn't
    needed."""

    def embed(self, text: str) -> tuple[float, ...]: ...
