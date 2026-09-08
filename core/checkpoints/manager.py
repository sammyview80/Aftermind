from typing import Any, Iterable, Optional

from core.checkpoints.triggers import DEFAULT_CHECKPOINT_TRIGGERS, should_checkpoint
from domain.enums.event_type import EventType
from domain.interfaces.checkpoint_store import CheckpointStore
from domain.models.checkpoint import Checkpoint
from domain.models.experience import Experience
from domain.models.scope import MemoryScope


class CheckpointManager:
    """Creates and retrieves checkpoints — the "I stopped here, continue
    from where I left off" mechanism that recall planning builds on."""

    def __init__(self, store: CheckpointStore) -> None:
        self._store = store

    def create(
        self,
        scope: Optional[MemoryScope],
        summary: str,
        memory_ids: Iterable[str] = (),
        last_experience_id: Optional[str] = None,
        reason: str = "",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Checkpoint:
        checkpoint = Checkpoint(
            scope=scope,
            summary=summary,
            memory_ids=tuple(memory_ids),
            last_experience_id=last_experience_id,
            reason=reason,
            metadata=metadata or {},
        )
        return self._store.save(checkpoint)

    def latest(self, scope: Optional[MemoryScope] = None) -> Optional[Checkpoint]:
        return self._store.latest(scope)

    def checkpoint_experience(
        self,
        experience: Experience,
        memory_ids: Iterable[str] = (),
        triggers: frozenset[EventType] = DEFAULT_CHECKPOINT_TRIGGERS,
    ) -> Optional[Checkpoint]:
        """Create a checkpoint for `experience` if it hit a trigger event
        (task completed/failed, agent handoff, ...); otherwise no-op."""
        if not should_checkpoint(experience, triggers):
            return None

        triggering_type = next(e.event_type for e in experience.events if e.event_type in triggers)
        summary = experience.output or experience.input

        return self.create(
            scope=experience.scope,
            summary=summary,
            memory_ids=memory_ids,
            last_experience_id=experience.experience_id,
            reason=triggering_type.value,
        )
