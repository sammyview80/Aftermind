from typing import Optional

from core.checkpoints.manager import CheckpointManager
from domain.enums.event_type import EventType
from domain.models.checkpoint import Checkpoint
from domain.models.event import Event
from domain.models.experience import Experience
from domain.models.scope import MemoryScope


class FakeCheckpointStore:
    def __init__(self) -> None:
        self._checkpoints: list[Checkpoint] = []

    def save(self, checkpoint: Checkpoint) -> Checkpoint:
        self._checkpoints.append(checkpoint)
        return checkpoint

    def latest(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        matching = [c for c in self._checkpoints if c.scope == scope] if scope else self._checkpoints
        return matching[-1] if matching else None


def test_create_saves_and_returns_checkpoint():
    store = FakeCheckpointStore()
    manager = CheckpointManager(store)
    scope = MemoryScope.of(tenant_id="t1")

    checkpoint = manager.create(scope=scope, goal="Build login flow", current="wiring session handling", memory_ids=["m1"], reason="task_completed")

    assert checkpoint.goal == "Build login flow"
    assert checkpoint.current == "wiring session handling"
    assert checkpoint.version == 1
    assert manager.latest(scope) is checkpoint


def test_latest_returns_none_when_no_checkpoints():
    manager = CheckpointManager(FakeCheckpointStore())
    assert manager.latest(MemoryScope.of(tenant_id="t1")) is None


def test_create_increments_version_per_scope():
    store = FakeCheckpointStore()
    manager = CheckpointManager(store)
    scope = MemoryScope.of(tenant_id="t1")

    first = manager.create(scope=scope, goal="first")
    second = manager.create(scope=scope, goal="second")

    assert first.version == 1
    assert second.version == 2
    assert manager.latest(scope) is second


def test_checkpoint_experience_creates_checkpoint_on_task_completed():
    manager = CheckpointManager(FakeCheckpointStore())
    scope = MemoryScope.of(tenant_id="t1")
    experience = Experience(
        experience_id="exp1",
        scope=scope,
        input="Build the login flow",
        events=[
            Event(event_type=EventType.USER_MESSAGE, payload={"text": "Build the login flow"}),
            Event(event_type=EventType.TASK_COMPLETED, payload={"result": "tests passed"}),
        ],
        output="Login flow implemented, tests passed",
    )

    checkpoint = manager.checkpoint_experience(experience, memory_ids=["m1"])

    assert checkpoint is not None
    assert checkpoint.goal == "Build the login flow"
    assert checkpoint.completed == ("tests passed",)
    assert checkpoint.current == "Login flow implemented, tests passed"
    assert checkpoint.last_experience_id == "exp1"
    assert checkpoint.reason == "task_completed"
    assert checkpoint.memory_ids == ("m1",)


def test_checkpoint_experience_returns_none_without_trigger_event():
    manager = CheckpointManager(FakeCheckpointStore())
    experience = Experience(events=[Event(event_type=EventType.USER_MESSAGE)])

    assert manager.checkpoint_experience(experience) is None
    assert manager.latest(experience.scope) is None


def test_checkpoint_experience_triggers_on_task_failed_and_handoff():
    manager = CheckpointManager(FakeCheckpointStore())

    failed = Experience(events=[Event(event_type=EventType.TASK_FAILED)], output="Ran out of retries")
    handoff = Experience(events=[Event(event_type=EventType.AGENT_HANDOFF)], output="Handing off to reviewer")

    assert manager.checkpoint_experience(failed).reason == "task_failed"
    assert manager.checkpoint_experience(handoff).reason == "agent_handoff"


def test_create_merges_omitted_fields_from_previous_checkpoint():
    store = FakeCheckpointStore()
    manager = CheckpointManager(store)
    scope = MemoryScope.of(tenant_id="t1")

    manager.create(
        scope=scope,
        goal="Build login flow",
        completed=["wired routes"],
        current="writing tests",
        blockers=["flaky CI"],
        next_steps=["fix CI"],
        memory_ids=["m1"],
    )

    updated = manager.create(scope=scope, current="tests passing")

    assert updated.goal == "Build login flow"
    assert updated.completed == ("wired routes",)
    assert updated.current == "tests passing"
    assert updated.blockers == ("flaky CI",)
    assert updated.next_steps == ("fix CI",)
    assert updated.memory_ids == ("m1",)
    assert updated.version == 2


def test_create_explicit_values_override_previous_checkpoint():
    store = FakeCheckpointStore()
    manager = CheckpointManager(store)
    scope = MemoryScope.of(tenant_id="t1")

    manager.create(scope=scope, goal="first", completed=["a"], blockers=["b"])
    updated = manager.create(scope=scope, goal="second", completed=["c"], blockers=[])

    assert updated.goal == "second"
    assert updated.completed == ("c",)
    assert updated.blockers == ("b",)


def test_latest_finds_a_checkpoint_saved_under_a_different_session_id():
    """A checkpoint must outlive the session it was created in — that's
    the entire point of "continue where I left off" across a new
    session. Scope is stabilized (execution levels stripped) at both
    create() and latest() so a new session_id/run_id doesn't hide it."""
    store = FakeCheckpointStore()
    manager = CheckpointManager(store)
    scope_session_1 = MemoryScope.of(tenant_id="t1", session_id="s1")
    scope_session_2 = MemoryScope.of(tenant_id="t1", session_id="s2")

    manager.create(scope=scope_session_1, goal="Build login flow")

    found = manager.latest(scope_session_2)
    assert found is not None
    assert found.goal == "Build login flow"


def test_create_increments_version_across_different_session_ids():
    store = FakeCheckpointStore()
    manager = CheckpointManager(store)

    first = manager.create(scope=MemoryScope.of(tenant_id="t1", session_id="s1"), goal="first")
    second = manager.create(scope=MemoryScope.of(tenant_id="t1", session_id="s2"), goal="second")

    assert first.version == 1
    assert second.version == 2
