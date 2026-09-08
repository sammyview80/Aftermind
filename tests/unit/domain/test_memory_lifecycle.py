from datetime import datetime, timezone
from types import MappingProxyType

import pytest

from domain.enums.memory_status import MemoryStatus
from domain.models.memory_lifecycle import MemoryLifecycle
from domain.models.scope import MemoryScope


def test_defaults():
    lifecycle = MemoryLifecycle(memory_id="m1")
    assert lifecycle.status == MemoryStatus.ACTIVE
    assert lifecycle.importance == 0.5
    assert lifecycle.decay_score == 0.0
    assert lifecycle.access_count == 0
    assert lifecycle.last_accessed_at is None
    assert lifecycle.valid_until is None
    assert isinstance(lifecycle.valid_from, datetime)
    assert lifecycle.valid_from.tzinfo == timezone.utc


def test_construct_with_all_fields():
    scope = MemoryScope.of(tenant_id="t1")
    now = datetime.now(timezone.utc)
    lifecycle = MemoryLifecycle(
        memory_id="m1",
        scope=scope,
        status=MemoryStatus.DECAYED,
        importance=0.8,
        confidence=0.9,
        decay_score=0.4,
        access_count=12,
        last_accessed_at=now,
        valid_until=now,
        metadata={"note": "x"},
    )

    assert lifecycle.scope is scope
    assert lifecycle.status == MemoryStatus.DECAYED
    assert lifecycle.importance == 0.8
    assert lifecycle.access_count == 12
    assert lifecycle.last_accessed_at == now
    assert lifecycle.valid_until == now
    assert lifecycle.metadata == {"note": "x"}


def test_metadata_is_immutable_mapping():
    lifecycle = MemoryLifecycle(memory_id="m1", metadata={"k": "v"})
    assert isinstance(lifecycle.metadata, MappingProxyType)
    with pytest.raises(TypeError):
        lifecycle.metadata["k"] = "changed"


def test_lifecycle_is_frozen():
    lifecycle = MemoryLifecycle(memory_id="m1")
    with pytest.raises(Exception):
        lifecycle.status = MemoryStatus.ARCHIVED


@pytest.mark.parametrize(
    "status,expected",
    [
        (MemoryStatus.ACTIVE, True),
        (MemoryStatus.DECAYED, True),
        (MemoryStatus.ARCHIVED, False),
        (MemoryStatus.EXPIRED, False),
        (MemoryStatus.FORGOTTEN, False),
    ],
)
def test_is_active_for_recall(status, expected):
    assert MemoryLifecycle(memory_id="m1", status=status).is_active_for_recall() is expected
