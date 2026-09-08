from typing import Optional

from domain.models.checkpoint import Checkpoint
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.serialize import dump_json, dump_scope_levels, load_dt_required, load_json, load_scope, scope_key


def _row_to_checkpoint(row) -> Checkpoint:
    return Checkpoint(
        checkpoint_id=row["checkpoint_id"],
        scope=load_scope(row["scope_levels"]),
        version=row["version"],
        goal=row["goal"],
        completed=tuple(load_json(row["completed"])),
        current=row["current"],
        blockers=tuple(load_json(row["blockers"])),
        next_steps=tuple(load_json(row["next_steps"])),
        memory_ids=tuple(load_json(row["memory_ids"])),
        last_experience_id=row["last_experience_id"],
        reason=row["reason"],
        metadata=load_json(row["metadata"]),
        created_at=load_dt_required(row["created_at"]),
    )


class SqliteCheckpointStore:
    """CheckpointStore backed by SQLite — versioned checkpoints survive
    an Aftermind restart, same as memories."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        with self._client.connect() as conn:
            conn.execute(
                """
                INSERT INTO checkpoints (
                    checkpoint_id, scope_key, scope_levels, version, goal, completed, current,
                    blockers, next_steps, memory_ids, last_experience_id, reason, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    checkpoint.checkpoint_id,
                    scope_key(checkpoint.scope),
                    dump_scope_levels(checkpoint.scope),
                    checkpoint.version,
                    checkpoint.goal,
                    dump_json(list(checkpoint.completed)),
                    checkpoint.current,
                    dump_json(list(checkpoint.blockers)),
                    dump_json(list(checkpoint.next_steps)),
                    dump_json(list(checkpoint.memory_ids)),
                    checkpoint.last_experience_id,
                    checkpoint.reason,
                    dump_json(dict(checkpoint.metadata)),
                    checkpoint.created_at.isoformat(),
                ),
            )
        return checkpoint

    def latest(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        with self._client.connect() as conn:
            row = conn.execute(
                "SELECT * FROM checkpoints WHERE scope_key = ? ORDER BY version DESC LIMIT 1",
                (scope_key(scope),),
            ).fetchone()
        return _row_to_checkpoint(row) if row else None
