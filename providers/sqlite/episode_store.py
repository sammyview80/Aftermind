from typing import Optional

from domain.enums.event_type import EventType
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.serialize import dump_json, dump_scope_levels, load_dt_required, load_json, load_scope, scope_key


def _event_to_dict(event: Event) -> dict:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "timestamp": event.timestamp.isoformat(),
        "payload": dict(event.payload),
        "source": event.source,
        "metadata": dict(event.metadata),
    }


def _event_from_dict(data: dict) -> Event:
    from datetime import datetime

    return Event(
        event_id=data["event_id"],
        event_type=EventType(data["event_type"]),
        timestamp=datetime.fromisoformat(data["timestamp"]),
        payload=data["payload"],
        source=data["source"],
        metadata=data["metadata"],
    )


def _row_to_experience(row) -> Experience:
    return Experience(
        experience_id=row["experience_id"],
        scope=load_scope(row["scope_levels"]),
        events=tuple(_event_from_dict(e) for e in load_json(row["events"])),
        input=row["input"],
        output=row["output"],
        success=bool(row["success"]) if row["success"] is not None else None,
        metadata=load_json(row["metadata"]),
        created_at=load_dt_required(row["created_at"]),
    )


class SqliteEpisodeStore:
    """EpisodeStore backed by SQLite — the raw-experience audit trail,
    kept independent of whether anything extracted from it was ever
    accepted as a Memory."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def save(self, experience: Experience) -> Experience:
        with self._client.connect() as conn:
            conn.execute(
                """
                INSERT INTO experiences (
                    experience_id, scope_key, scope_levels, input, output, outcome, success,
                    events, metadata, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experience_id) DO NOTHING
                """,
                (
                    experience.experience_id,
                    scope_key(experience.scope),
                    dump_scope_levels(experience.scope),
                    experience.input,
                    experience.output,
                    experience.outcome.value,
                    None if experience.success is None else int(experience.success),
                    dump_json([_event_to_dict(e) for e in experience.events]),
                    dump_json(dict(experience.metadata)),
                    experience.created_at.isoformat(),
                ),
            )
        return experience

    def get(self, experience_id: str) -> Optional[Experience]:
        with self._client.connect() as conn:
            row = conn.execute(
                "SELECT * FROM experiences WHERE experience_id = ?", (experience_id,)
            ).fetchone()
        return _row_to_experience(row) if row else None
