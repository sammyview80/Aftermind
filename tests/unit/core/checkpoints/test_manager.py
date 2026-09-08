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

    checkpoint = manager.create(scope=scope, summary="Login flow implemented", memory_ids=["m1"], reason="task_completed")

    assert checkpoint.summary == "Login flow implemented"
    assert manager.latest(scope) is checkpoint


def test_latest_returns_none_when_no_checkpoints():
    manager = CheckpointManager(FakeCheckpointStore())
    assert manager.latest(MemoryScope.of(tenant_id="t1")) is None


def test_latest_returns_most_recent_for_scope():
    store = FakeCheckpointStore()
    manager = CheckpointManager(store)
    scope = MemoryScope.of(tenant_id="t1")

    manager.create(scope=scope, summary="first")
    second = manager.create(scope=scope, summary="second")

    assert manager.latest(scope) is second


def test_checkpoint_experience_creates_checkpoint_on_task_completed():
    manager = CheckpointManager(FakeCheckpointStore())
    scope = MemoryScope.of(tenant_id="t1")
    experience = Experience(
        experience_id="exp1",
        scope=scope,
        events=[Event(event_type=EventType.TASK_COMPLETED)],
        output="Login flow implemented, tests passed",
    )

    checkpoint = manager.checkpoint_experience(experience, memory_ids=["m1"])

    assert checkpoint is not None
    assert checkpoint.summary == "Login flow implemented, tests passed"
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
