import math
from array import array
from typing import Optional

from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.serialize import now_iso, scope_key


def _pack(embedding: tuple[float, ...]) -> bytes:
    return array("f", embedding).tobytes()


def _unpack(blob: bytes) -> array:
    values = array("f")
    values.frombytes(blob)
    return values


def _cosine_similarity(a: array, b: array) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


class SqliteVectorStore:
    """Local embedding index for semantic recall — cosine similarity
    computed in Python over rows fetched by scope. Fine at Aftermind's
    scale (one repo/project's memory, not a multi-tenant corpus); swap
    for sqlite-vec or a real ANN index if a scope's memory count ever
    makes a full scan slow."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def upsert(self, memory_id: str, scope: Optional[MemoryScope], embedding: tuple[float, ...], model: str) -> None:
        with self._client.connect() as conn:
            conn.execute(
                """
                INSERT INTO memory_embeddings (memory_id, scope_key, embedding, model, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    scope_key=excluded.scope_key, embedding=excluded.embedding,
                    model=excluded.model, created_at=excluded.created_at
                """,
                (memory_id, scope_key(scope), _pack(embedding), model, now_iso()),
            )

    def search_similar(
        self, scope: Optional[MemoryScope], query_embedding: tuple[float, ...], limit: int = 5
    ) -> list[tuple[str, float]]:
        query_vec = array("f", query_embedding)
        with self._client.connect() as conn:
            rows = conn.execute(
                "SELECT memory_id, embedding FROM memory_embeddings WHERE scope_key = ?", (scope_key(scope),)
            ).fetchall()

        scored = [(row["memory_id"], _cosine_similarity(query_vec, _unpack(row["embedding"]))) for row in rows]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]

    def delete(self, memory_id: str) -> None:
        with self._client.connect() as conn:
            conn.execute("DELETE FROM memory_embeddings WHERE memory_id = ?", (memory_id,))
