from typing import Optional

from domain.enums.preference_source import PreferenceSource
from domain.models.preference import Preference
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.serialize import dump_json, dump_scope_levels, load_dt_required, load_json, load_scope, scope_key


def _row_to_preference(row) -> Preference:
    return Preference(
        preference_id=row["preference_id"],
        scope=load_scope(row["scope_levels"]),
        dimension=row["dimension"],
        value=load_json(row["value"]),
        confidence=row["confidence"],
        evidence_count=row["evidence_count"],
        source=PreferenceSource(row["source"]),
        version=row["version"],
        superseded_by=row["superseded_by"],
        created_at=load_dt_required(row["created_at"]),
        updated_at=load_dt_required(row["updated_at"]),
    )


class SqlitePreferenceStore:
    """PreferenceStore backed by SQLite — an upsert-by-id table (unlike
    the append-only `checkpoints`/`memories` tables) since a preference
    row is mutated in place while the same value keeps being observed."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def save(self, preference: Preference) -> Preference:
        with self._client.connect() as conn:
            conn.execute(
                """
                INSERT INTO preferences (
                    preference_id, scope_key, scope_levels, dimension, value, confidence,
                    evidence_count, source, version, superseded_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(preference_id) DO UPDATE SET
                    value = excluded.value,
                    confidence = excluded.confidence,
                    evidence_count = excluded.evidence_count,
                    source = excluded.source,
                    version = excluded.version,
                    superseded_by = excluded.superseded_by,
                    updated_at = excluded.updated_at
                """,
                (
                    preference.preference_id,
                    scope_key(preference.scope),
                    dump_scope_levels(preference.scope),
                    preference.dimension,
                    dump_json(dict(preference.value)),
                    preference.confidence,
                    preference.evidence_count,
                    preference.source.value,
                    preference.version,
                    preference.superseded_by,
                    preference.created_at.isoformat(),
                    preference.updated_at.isoformat(),
                ),
            )
        return preference

    def latest_by_dimension(self, scope: Optional[MemoryScope], dimension: str) -> Optional[Preference]:
        with self._client.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM preferences
                WHERE scope_key = ? AND dimension = ? AND superseded_by IS NULL
                ORDER BY version DESC LIMIT 1
                """,
                (scope_key(scope), dimension),
            ).fetchone()
        return _row_to_preference(row) if row else None

    def list_active(self, scope: Optional[MemoryScope]) -> tuple[Preference, ...]:
        with self._client.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM preferences WHERE scope_key = ? AND superseded_by IS NULL ORDER BY dimension",
                (scope_key(scope),),
            ).fetchall()
        return tuple(_row_to_preference(row) for row in rows)
