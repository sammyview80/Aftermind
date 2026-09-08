from core.lifecycle.archival import archive
from domain.enums.memory_status import MemoryStatus
from domain.models.memory_lifecycle import MemoryLifecycle


def test_archive_sets_status_and_reason():
    lifecycle = MemoryLifecycle(memory_id="m1")
    archived = archive(lifecycle, reason="superseded_by:m2")

    assert archived.status == MemoryStatus.ARCHIVED
    assert archived.metadata["archived_reason"] == "superseded_by:m2"
    assert "archived_at" in archived.metadata


def test_archive_preserves_existing_metadata():
    lifecycle = MemoryLifecycle(memory_id="m1", metadata={"custom": "value"})
    archived = archive(lifecycle)
    assert archived.metadata["custom"] == "value"
    assert archived.metadata["archived_reason"] == "superseded"
