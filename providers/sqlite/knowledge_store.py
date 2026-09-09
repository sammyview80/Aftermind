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


_STOPWORDS = frozenset(
    {"the", "a", "an", "and", "or", "but", "for", "with", "this", "that", "from", "into", "onto",
     "is", "are", "was", "were", "be", "to", "of", "on", "in", "at", "it", "as", "by", "we", "you"}
)


def _words(text: str) -> set[str]:
    return {w.strip(".,!?").lower() for w in text.split() if w.strip(".,!?")}


def _fts_match_query(text: str) -> Optional[str]:
    """Build an FTS5 MATCH expression from `text`'s meaningful words,
    OR-joined so any overlapping term counts as a hit (bm25 still ranks
    by how many/how rare) — each word is double-quoted as a literal
    phrase token so punctuation/FTS5 operator characters in the source
    text (hyphens, colons, asterisks) can't be interpreted as query
    syntax. Returns None when there's nothing worth matching on."""
    words = [w for w in _words(text) if w not in _STOPWORDS]
    if not words:
        return None
    return " OR ".join('"' + w.replace('"', '""') + '"' for w in words)


class SqliteKnowledgeStore:
    """KnowledgeStore backed by SQLite — Aftermind's durable memory
    store. `search`/`history` use FTS5 (BM25-ranked) full-text matching
    over memory content rather than naive Python word-overlap scoring —
    real keyword search, not just exact-vocabulary-match Jaccard."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def _fts_search(self, query: str, scope: Optional[MemoryScope], limit: int, live: bool) -> list[Memory]:
        match = _fts_match_query(query)
        if match is None:
            return []
        superseded_clause = "m.superseded_by IS NULL" if live else "m.superseded_by IS NOT NULL"
        with self._client.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT m.* FROM memories m
                JOIN memories_fts f ON f.rowid = m.rowid
                WHERE m.scope_key = ? AND {superseded_clause} AND memories_fts MATCH ?
                ORDER BY bm25(memories_fts)
                LIMIT ?
                """,
                (scope_key(scope), match, limit),
            ).fetchall()
        return [_row_to_memory(row) for row in rows]

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        return self._fts_search(query, scope, limit, live=True)

    def history(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[Memory]:
        return self._fts_search(query, scope, limit, live=False)

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
