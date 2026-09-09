import sqlite3

from providers.sqlite.client import SqliteClient


def test_migrate_adds_memory_domain_column_to_a_pre_existing_memories_table(tmp_path):
    db_path = str(tmp_path / "old.db")
    # Simulate a database created before `memory_domain` existed.
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE memories (
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
        )
        """
    )
    conn.commit()
    conn.close()

    SqliteClient(db_path)

    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    conn.close()
    assert "memory_domain" in columns


def test_migrate_is_idempotent_across_reopens(tmp_path):
    db_path = str(tmp_path / "new.db")
    SqliteClient(db_path)
    SqliteClient(db_path)  # must not raise on the already-migrated table
