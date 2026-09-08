from typing import Any, Iterable, Optional

from core.checkpoints.summarizer import CheckpointSummarizer
from core.checkpoints.triggers import DEFAULT_CHECKPOINT_TRIGGERS, should_checkpoint
from domain.enums.event_type import EventType
from domain.interfaces.checkpoint_store import CheckpointStore
from domain.models.checkpoint import Checkpoint
from domain.models.experience import Experience
from domain.models.scope import MemoryScope


class CheckpointManager:
    """Creates and retrieves checkpoints — the "I stopped here, continue
    from where I left off" mechanism that recall planning builds on."""

    def __init__(self, store: CheckpointStore, summarizer: Optional[CheckpointSummarizer] = None) -> None:
        self._store = store
        self._summarizer = summarizer or CheckpointSummarizer()

    def create(
        self,
        scope: Optional[MemoryScope],
        goal: str = "",
        completed: Iterable[str] = (),
        current: str = "",
        blockers: Iterable[str] = (),
        next_steps: Iterable[str] = (),
        memory_ids: Iterable[str] = (),
        last_experience_id: Optional[str] = None,
        reason: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Checkpoint:
        # A checkpoint outlives the run/session it was created in — "continue
        # where I left off" means finding it from a *new* session, so it's
        # stored and looked up under stabilized (execution-scope-stripped) scope.
        scope = scope.stable() if scope is not None else None
        previous = self._store.latest(scope)
        checkpoint = Checkpoint(
            scope=scope,
            version=(previous.version + 1) if previous else 1,
            goal=goal,
            completed=tuple(completed),
            current=current,
            blockers=tuple(blockers),
            next_steps=tuple(next_steps),
            memory_ids=tuple(memory_ids),
            last_experience_id=last_experience_id,
            reason=reason,
            metadata=metadata or {},
        )
        return self._store.save(checkpoint)

    def latest(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        return self._store.latest(scope.stable() if scope is not None else None)

    def checkpoint_experience(
        self,
        experience: Experience,
        memory_ids: Iterable[str] = (),
        triggers: frozenset[EventType] = DEFAULT_CHECKPOINT_TRIGGERS,
    ) -> Optional[Checkpoint]:
        """Summarize and create a checkpoint for `experience` if it hit a
        trigger event (task completed/failed, agent handoff, ...);
        otherwise no-op."""
        if not should_checkpoint(experience, triggers):
            return None

        triggering_type = next(e.event_type for e in experience.events if e.event_type in triggers)
        summary = self._summarizer.summarize(experience)

        return self.create(
            scope=experience.scope,
            goal=summary.goal,
            completed=summary.completed,
            current=summary.current,
            blockers=summary.blockers,
            next_steps=summary.next_steps,
            memory_ids=memory_ids,
            last_experience_id=experience.experience_id,
            reason=triggering_type.value,
        )
