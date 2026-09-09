from typing import Optional

from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.serialize import dump_scope_levels, now_iso, scope_key


class SqlitePreferenceEvidenceStore:
    """Durable, append-only buffer of raw text pending LLM preference
    reconciliation — cleared each time the reconciler consumes it."""

    def __init__(self, client: SqliteClient) -> None:
        self._client = client

    def append(self, scope: Optional[MemoryScope], text: str) -> None:
        with self._client.connect() as conn:
            conn.execute(
                "INSERT INTO preference_evidence (scope_key, scope_levels, text, created_at) VALUES (?, ?, ?, ?)",
                (scope_key(scope), dump_scope_levels(scope), text, now_iso()),
            )

    def recent(self, scope: Optional[MemoryScope]) -> tuple[str, ...]:
        with self._client.connect() as conn:
            rows = conn.execute(
                "SELECT text FROM preference_evidence WHERE scope_key = ? ORDER BY evidence_id",
                (scope_key(scope),),
            ).fetchall()
        return tuple(row["text"] for row in rows)

    def clear(self, scope: Optional[MemoryScope]) -> None:
        with self._client.connect() as conn:
            conn.execute("DELETE FROM preference_evidence WHERE scope_key = ?", (scope_key(scope),))
