import sqlite3
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = "./aftermind.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    scope_levels TEXT NOT NULL,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    entities TEXT NOT NULL,
    relationships TEXT NOT NULL,
    confidence REAL NOT NULL,
    version INTEGER NOT NULL,
    superseded_by TEXT,
    source_candidate_ids TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_scope ON memories(scope_key);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    scope_levels TEXT NOT NULL,
    version INTEGER NOT NULL,
    goal TEXT NOT NULL,
    completed TEXT NOT NULL,
    current TEXT NOT NULL,
    blockers TEXT NOT NULL,
    next_steps TEXT NOT NULL,
    memory_ids TEXT NOT NULL,
    last_experience_id TEXT,
    reason TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_scope ON checkpoints(scope_key, created_at);

CREATE TABLE IF NOT EXISTS lifecycle (
    memory_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    scope_levels TEXT NOT NULL,
    status TEXT NOT NULL,
    importance REAL NOT NULL,
    confidence REAL NOT NULL,
    decay_score REAL NOT NULL,
    access_count INTEGER NOT NULL,
    last_accessed_at TEXT,
    valid_from TEXT NOT NULL,
    valid_until TEXT,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_lifecycle_scope ON lifecycle(scope_key);

CREATE TABLE IF NOT EXISTS experiences (
    experience_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    scope_levels TEXT NOT NULL,
    input TEXT NOT NULL,
    output TEXT NOT NULL,
    outcome TEXT NOT NULL,
    success INTEGER,
    events TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory_decisions (
    decision_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    action TEXT NOT NULL,
    target_memory_id TEXT,
    evidence_memory_ids TEXT NOT NULL,
    confidence REAL NOT NULL,
    reasoning TEXT NOT NULL,
    metadata TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class SqliteClient:
    """Owns the file-backed SQLite database used as Aftermind's Phase 1
    durable store (experiences, memories, checkpoints, memory decisions,
    lifecycle metadata). A fresh connection per operation — simplest
    correct thing for SQLite under FastAPI's threadpool, and cheap for a
    local file. Swap for a Postgres-backed client behind the same
    Protocols later without touching core/.
    """

    def __init__(self, path: str = DEFAULT_DB_PATH) -> None:
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
