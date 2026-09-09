import json

from apps import cli
from domain.models.memory import Memory
from domain.models.scope import MemoryScope
from providers.sqlite.client import SqliteClient
from providers.sqlite.knowledge_store import SqliteKnowledgeStore


def _seed(db_path):
    store = SqliteKnowledgeStore(SqliteClient(db_path))
    scope = MemoryScope.of(tenant_id="t1")
    keep = store.save(Memory(scope=scope, content="We decided the billing worker uses RabbitMQ."))
    junk = [
        store.save(Memory(scope=scope, content='Tool read_file result: {"content": "x"}')),
        store.save(Memory(scope=scope, content="what database does Aftermind use")),
        store.save(Memory(scope=scope, content="also commit and push")),
    ]
    return store, keep, junk


def test_memory_audit_dry_run_reports_rejections_without_deleting(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "a.db")
    store, keep, junk = _seed(db_path)
    monkeypatch.setenv("DATABASE_PATH", db_path)
    from apps.api import deps

    deps.get_settings.cache_clear()
    deps.get_sqlite_client.cache_clear()

    assert cli.main(["memory", "audit"]) == 0

    out = capsys.readouterr().out
    summary, _ = json.JSONDecoder().raw_decode(out)
    assert summary["memories"] == 4
    assert summary["would_reject"] == 3
    assert summary["by_reason"] == {"tool_output": 1, "question": 1, "directive": 1}
    assert store.get(junk[0].memory_id) is not None  # dry run
    deps.get_settings.cache_clear()
    deps.get_sqlite_client.cache_clear()


def test_memory_audit_purge_deletes_rejected_rows_after_backup(tmp_path, monkeypatch, capsys):
    db_path = str(tmp_path / "a.db")
    store, keep, junk = _seed(db_path)
    monkeypatch.setenv("DATABASE_PATH", db_path)
    from apps.api import deps

    deps.get_settings.cache_clear()
    deps.get_sqlite_client.cache_clear()

    assert cli.main(["memory", "audit", "--purge"]) == 0

    assert store.get(keep.memory_id) is not None
    assert all(store.get(j.memory_id) is None for j in junk)
    assert list(tmp_path.glob("a.db.bak-audit-*"))
    assert '"purged": 3' in capsys.readouterr().out
    deps.get_settings.cache_clear()
    deps.get_sqlite_client.cache_clear()
