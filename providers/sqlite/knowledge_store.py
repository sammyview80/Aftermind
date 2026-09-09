from typing import Optional

from domain.enums.memory_domain import MemoryDomain
from domain.enums.memory_type import MemoryType
from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.serialize import (
    dump_json,
    dump_scope_levels,
    load_dt_required,
    load_json,
    load_scope,
    scope_key,
)


def _row_to_memory(row) -> Memory:
    return Memory(
        memory_id=row["memory_id"],
        scope=load_scope(row["scope_levels"]),
        content=row["content"],
        memory_type=MemoryType(row["memory_type"]),
        memory_domain=MemoryDomain(row["memory_domain"]),
        entities=tuple(load_json(row["entities"])),
        relationships=tuple(load_json(row["relationships"])),
        confidence=row["confidence"],
        version=row["version"],
        superseded_by=row["superseded_by"],
        source_candidate_ids=tuple(load_json(row["source_candidate_ids"])),
        metadata=load_json(row["metadata"]),
        created_at=load_dt_required(row["created_at"]),
        updated_at=load_dt_required(row["updated_at"]),
    )


def _words(text: str) -> set[str]:
    return {w.strip(".,!?").lower() for w in text.split() if w.strip(".,!?")}


class SqliteKnowledgeStore:
    """KnowledgeStore backed by SQLite — Aftermind's Phase 1 durable
    memory store. `search` pulls candidates by scope from disk and ranks
    by word overlap in Python (fine at this scale; swap for pgvector/
    full-text search once volume warrants it)."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        query_words = _words(query)

        def overlap(memory: Memory) -> float:
            memory_words = _words(memory.content)
            if not query_words or not memory_words:
                return 0.0
            return len(query_words & memory_words) / len(query_words | memory_words)

        with self._client.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE scope_key = ? AND superseded_by IS NULL", (scope_key(scope),)
            ).fetchall()

        candidates = [_row_to_memory(row) for row in rows]
        ranked = sorted((m for m in candidates if overlap(m) > 0), key=overlap, reverse=True)
        return ranked[:limit]

    def history(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        query_words = _words(query)

        def overlap(memory: Memory) -> float:
            memory_words = _words(memory.content)
            if not query_words or not memory_words:
                return 0.0
            return len(query_words & memory_words) / len(query_words | memory_words)

        with self._client.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE scope_key = ? AND superseded_by IS NOT NULL", (scope_key(scope),)
            ).fetchall()

        candidates = [_row_to_memory(row) for row in rows]
        ranked = sorted((m for m in candidates if overlap(m) > 0), key=overlap, reverse=True)
        return ranked[:limit]

    def get(self, memory_id: str) -> Optional[Memory]:
        with self._client.connect() as conn:
            row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
        return _row_to_memory(row) if row else None

    def list_all(self, scope: Optional[MemoryScope] = None, limit: int = 1000) -> list[Memory]:
        with self._client.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memories WHERE scope_key = ? AND superseded_by IS NULL LIMIT ?",
                (scope_key(scope), limit),
            ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def save(self, memory: Memory) -> Memory:
        with self._client.connect() as conn:
            conn.execute(
                """
                INSERT INTO memories (
                    memory_id, scope_key, scope_levels, content, memory_type, memory_domain, entities,
                    relationships, confidence, version, superseded_by, source_candidate_ids,
                    metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    scope_key=excluded.scope_key, scope_levels=excluded.scope_levels,
                    content=excluded.content, memory_type=excluded.memory_type,
                    memory_domain=excluded.memory_domain,
                    entities=excluded.entities, relationships=excluded.relationships,
                    confidence=excluded.confidence, version=excluded.version,
                    superseded_by=excluded.superseded_by,
                    source_candidate_ids=excluded.source_candidate_ids,
                    metadata=excluded.metadata, updated_at=excluded.updated_at
                """,
                (
                    memory.memory_id,
                    scope_key(memory.scope),
                    dump_scope_levels(memory.scope),
                    memory.content,
                    memory.memory_type.value,
                    memory.memory_domain.value,
                    dump_json(list(memory.entities)),
                    dump_json(list(memory.relationships)),
                    memory.confidence,
                    memory.version,
                    memory.superseded_by,
                    dump_json(list(memory.source_candidate_ids)),
                    dump_json(dict(memory.metadata)),
                    memory.created_at.isoformat(),
                    memory.updated_at.isoformat(),
                ),
            )
        return memory
