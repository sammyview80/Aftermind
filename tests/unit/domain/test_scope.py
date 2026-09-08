from types import MappingProxyType

import pytest

from domain.models.scope import MemoryScope


def test_of_drops_none_values():
    scope = MemoryScope.of(tenant_id="t1", workspace_id=None, user_id="u1")
    assert scope.levels == {"tenant_id": "t1", "user_id": "u1"}


def test_get_returns_value_or_none():
    scope = MemoryScope.of(tenant_id="t1")
    assert scope.get("tenant_id") == "t1"
    assert scope.get("workspace_id") is None


def test_with_levels_adds_updates_and_removes():
    scope = MemoryScope.of(tenant_id="t1", workspace_id="w1")

    added = scope.with_levels(project_id="p1")
    assert added.levels == {"tenant_id": "t1", "workspace_id": "w1", "project_id": "p1"}

    updated = scope.with_levels(tenant_id="t2")
    assert updated.levels == {"tenant_id": "t2", "workspace_id": "w1"}

    removed = scope.with_levels(workspace_id=None)
    assert removed.levels == {"tenant_id": "t1"}

    # original untouched
    assert scope.levels == {"tenant_id": "t1", "workspace_id": "w1"}


def test_key_builds_hierarchy_key_with_wildcards():
    scope = MemoryScope.of(tenant_id="t1", project_id="p1")
    key = scope.key(hierarchy=("tenant_id", "workspace_id", "project_id"))
    assert key == "t1:*:p1"


def test_key_at_returns_prefix():
    scope = MemoryScope.of(tenant_id="t1", workspace_id="w1", project_id="p1")
    hierarchy = ("tenant_id", "workspace_id", "project_id")
    assert scope.key_at("workspace_id", hierarchy=hierarchy) == "t1:w1"


def test_key_at_raises_when_level_missing():
    scope = MemoryScope.of(tenant_id="t1")
    hierarchy = ("tenant_id", "workspace_id", "project_id")
    with pytest.raises(ValueError):
        scope.key_at("project_id", hierarchy=hierarchy)


def test_key_at_raises_when_level_not_in_hierarchy():
    scope = MemoryScope.of(tenant_id="t1")
    with pytest.raises(ValueError):
        scope.key_at("not_a_level", hierarchy=("tenant_id",))


def test_stable_removes_execution_levels():
    scope = MemoryScope.of(tenant_id="t1", session_id="s1", run_id="r1")
    stable = scope.stable(execution_levels=frozenset({"session_id", "run_id"}))
    assert stable.levels == {"tenant_id": "t1"}


def test_is_execution_scope_detects_session_or_run():
    exec_levels = frozenset({"session_id", "run_id"})
    assert MemoryScope.of(session_id="s1").is_execution_scope(exec_levels)
    assert MemoryScope.of(run_id="r1").is_execution_scope(exec_levels)
    assert not MemoryScope.of(tenant_id="t1").is_execution_scope(exec_levels)


def test_levels_are_immutable_mapping():
    scope = MemoryScope.of(tenant_id="t1")
    assert isinstance(scope.levels, MappingProxyType)
    with pytest.raises(TypeError):
        scope.levels["tenant_id"] = "t2"
    with pytest.raises(TypeError):
        del scope.levels["tenant_id"]


def test_scope_dataclass_is_frozen():
    scope = MemoryScope.of(tenant_id="t1")
    with pytest.raises(Exception):
        scope.levels = {}
