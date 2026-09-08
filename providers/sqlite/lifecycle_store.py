from typing import Optional

from domain.enums.memory_status import MemoryStatus
from domain.models.memory_lifecycle import MemoryLifecycle
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.serialize import (
    dump_dt,
    dump_json,
    dump_scope_levels,
    load_dt,
    load_dt_required,
    load_json,
    load_scope,
    scope_key,
)


def _row_to_lifecycle(row) -> MemoryLifecycle:
    return MemoryLifecycle(
        memory_id=row["memory_id"],
        scope=load_scope(row["scope_levels"]),
        status=MemoryStatus(row["status"]),
        importance=row["importance"],
        confidence=row["confidence"],
        decay_score=row["decay_score"],
        access_count=row["access_count"],
        last_accessed_at=load_dt(row["last_accessed_at"]),
        valid_from=load_dt_required(row["valid_from"]),
        valid_until=load_dt(row["valid_until"]),
        metadata=load_json(row["metadata"]),
        created_at=load_dt_required(row["created_at"]),
        updated_at=load_dt_required(row["updated_at"]),
    )


class SqliteLifecycleStore:
    """LifecycleStore backed by SQLite."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def get(self, memory_id: str, scope: Optional[MemoryScope] = None) -> Optional[MemoryLifecycle]:
        with self._client.connect() as conn:
            row = conn.execute("SELECT * FROM lifecycle WHERE memory_id = ?", (memory_id,)).fetchone()
        return _row_to_lifecycle(row) if row else None

    def save(self, lifecycle: MemoryLifecycle) -> MemoryLifecycle:
        with self._client.connect() as conn:
            conn.execute(
                """
                INSERT INTO lifecycle (
                    memory_id, scope_key, scope_levels, status, importance, confidence, decay_score,
                    access_count, last_accessed_at, valid_from, valid_until, metadata, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(memory_id) DO UPDATE SET
                    scope_key=excluded.scope_key, scope_levels=excluded.scope_levels,
                    status=excluded.status, importance=excluded.importance,
                    confidence=excluded.confidence, decay_score=excluded.decay_score,
                    access_count=excluded.access_count, last_accessed_at=excluded.last_accessed_at,
                    valid_until=excluded.valid_until, metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                (
                    lifecycle.memory_id,
                    scope_key(lifecycle.scope),
                    dump_scope_levels(lifecycle.scope),
                    lifecycle.status.value,
                    lifecycle.importance,
                    lifecycle.confidence,
                    lifecycle.decay_score,
                    lifecycle.access_count,
                    dump_dt(lifecycle.last_accessed_at),
                    lifecycle.valid_from.isoformat(),
                    dump_dt(lifecycle.valid_until),
                    dump_json(dict(lifecycle.metadata)),
                    lifecycle.created_at.isoformat(),
                    lifecycle.updated_at.isoformat(),
                ),
            )
        return lifecycle

    def list_all(self, scope: Optional[MemoryScope] = None) -> list[MemoryLifecycle]:
        with self._client.connect() as conn:
            if scope is None:
                rows = conn.execute("SELECT * FROM lifecycle").fetchall()
            else:
                rows = conn.execute("SELECT * FROM lifecycle WHERE scope_key = ?", (scope_key(scope),)).fetchall()
        return [_row_to_lifecycle(row) for row in rows]
