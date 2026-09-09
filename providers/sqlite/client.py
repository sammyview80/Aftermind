import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = "./aftermind.db"
DEFAULT_BUSY_TIMEOUT_SECONDS = 5.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    memory_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    scope_levels TEXT NOT NULL,
    content TEXT NOT NULL,
    memory_type TEXT NOT NULL,
    memory_domain TEXT NOT NULL DEFAULT 'project',
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

CREATE TABLE IF NOT EXISTS sync_jobs (
    job_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    scope_levels TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL,
    max_attempts INTEGER NOT NULL,
    next_attempt_at TEXT NOT NULL,
    last_error TEXT,
    trace_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sync_jobs_due ON sync_jobs(status, next_attempt_at);

CREATE TABLE IF NOT EXISTS preferences (
    preference_id TEXT PRIMARY KEY,
    scope_key TEXT NOT NULL,
    scope_levels TEXT NOT NULL,
    dimension TEXT NOT NULL,
    value TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence_count INTEGER NOT NULL,
    source TEXT NOT NULL,
    version INTEGER NOT NULL,
    superseded_by TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_preferences_scope_dimension ON preferences(scope_key, dimension);

CREATE TABLE IF NOT EXISTS preference_evidence (
    evidence_id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_key TEXT NOT NULL,
    scope_levels TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_preference_evidence_scope ON preference_evidence(scope_key, evidence_id);
"""


class SqliteClient:
    """Owns the file-backed SQLite database used as Aftermind's canonical
    durable store (experiences, memories, checkpoints, memory decisions,
    lifecycle metadata, and the sync-job outbox).

    Connections: one fresh connection per operation by default — simplest
    correct thing under FastAPI's threadpool plus a background sync
    worker — *unless* the calling thread is inside `transaction()`, in
    which case every `connect()` on that thread joins the open
    transaction's connection and commits/rolls back with it. That is how
    "write memory + enqueue its sync job" becomes atomic without the
    individual stores knowing about each other.

    WAL journal mode lets the worker thread read while a request thread
    writes; busy_timeout makes concurrent writers wait instead of
    failing with "database is locked".
    """

    def __init__(self, path: str = DEFAULT_DB_PATH, busy_timeout: float = DEFAULT_BUSY_TIMEOUT_SECONDS) -> None:
        self.path = path
        self._busy_timeout = busy_timeout
        self._local = threading.local()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # Schema setup on a bare autocommit connection: journal_mode can't
        # change inside a transaction, and executescript() issues its own
        # COMMIT, so neither belongs inside connect()'s BEGIN/COMMIT.
        setup = self._open()
        try:
            if path != ":memory:":
                setup.execute("PRAGMA journal_mode=WAL")
            setup.executescript(_SCHEMA)
            self._migrate(setup)
        finally:
            setup.close()

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Additive schema changes for databases created before a column
        existed. `CREATE TABLE IF NOT EXISTS` in `_SCHEMA` only handles
        brand-new tables — an existing `memories` table from before
        `memory_domain` was added needs this to pick the column up."""
        try:
            conn.execute("ALTER TABLE memories ADD COLUMN memory_domain TEXT NOT NULL DEFAULT 'project'")
        except sqlite3.OperationalError as exc:
            if "duplicate column name" not in str(exc):
                raise

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=self._busy_timeout, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute(f"PRAGMA busy_timeout={int(self._busy_timeout * 1000)}")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def connect(self):
        """A connection for one operation. Inside `transaction()` on this
        thread it is the transaction's connection (no commit here); otherwise
        it is a fresh autocommit-per-statement connection wrapped in its own
        BEGIN/COMMIT so multi-statement stores stay atomic."""
        active = getattr(self._local, "txn_conn", None)
        if active is not None:
            yield active
            return

        conn = self._open()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            conn.close()

    @contextmanager
    def transaction(self):
        """UnitOfWork: every store write on this thread until the block
        exits joins one BEGIN IMMEDIATE transaction. Reentrant — a nested
        call joins the outer transaction rather than starting its own."""
        if getattr(self._local, "txn_conn", None) is not None:
            yield
            return

        conn = self._open()
        self._local.txn_conn = conn
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        finally:
            self._local.txn_conn = None
            conn.close()

    def backup(self, destination: str) -> str:
        """Consistent online snapshot of the live database (sqlite3's
        backup API, safe while the API/worker keep writing). Returns the
        destination path."""
        Path(destination).parent.mkdir(parents=True, exist_ok=True)
        source = self._open()
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        return destination

    def integrity_check(self) -> bool:
        with self.connect() as conn:
            row = conn.execute("PRAGMA integrity_check").fetchone()
        return bool(row) and row[0] == "ok"
