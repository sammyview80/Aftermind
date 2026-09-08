from datetime import datetime
from typing import Iterable, Optional

from core.lifecycle import archival, decay, forgetting, reinforcement
from domain.enums.memory_status import MemoryStatus
from domain.interfaces.lifecycle_store import LifecycleStore
from domain.models.knowledge_document import KnowledgeDocument
from domain.models.memory import Memory
from domain.models.memory_lifecycle import MemoryLifecycle
from domain.models.scope import MemoryScope


class LifecycleManager:
    """Orchestrates the four lifecycle operations (reinforce/decay/
    archive/forget) against a LifecycleStore. Doesn't own
    KnowledgeStore/DocumentStore itself — cascade_provenance returns
    cleaned copies for the caller to persist via their own stores,
    keeping this package's only dependency the lifecycle records
    themselves.
    """

    def __init__(self, store: LifecycleStore) -> None:
        self._store = store

    def get_or_create(self, memory: Memory) -> MemoryLifecycle:
        existing = self._store.get(memory.memory_id, scope=memory.scope)
        if existing is not None:
            return existing
        return self._store.save(
            MemoryLifecycle(
                memory_id=memory.memory_id,
                scope=memory.scope,
                confidence=memory.confidence,
                valid_from=memory.created_at,
            )
        )

    def status_of(self, memory_id: str, scope: Optional[MemoryScope] = None) -> MemoryStatus:
        """The recorded lifecycle status for one memory, defaulting to
        ACTIVE if no lifecycle record exists yet (e.g. ranking a memory
        recalled before get_or_create ever ran for it)."""
        lifecycle = self._store.get(memory_id, scope=scope)
        return lifecycle.status if lifecycle is not None else MemoryStatus.ACTIVE

    def record_access(
        self, memory_id: str, scope: Optional[MemoryScope] = None, at: Optional[datetime] = None
    ) -> MemoryLifecycle:
        """Memory retrieved often -> strengthen."""
        lifecycle = self._store.get(memory_id, scope=scope) or MemoryLifecycle(memory_id=memory_id, scope=scope)
        return self._store.save(reinforcement.reinforce(lifecycle, at=at))

    def run_decay(
        self, memory_id: str, scope: Optional[MemoryScope] = None, at: Optional[datetime] = None
    ) -> Optional[MemoryLifecycle]:
        """Memory never used -> decay (and eventually expire)."""
        lifecycle = self._store.get(memory_id, scope=scope)
        if lifecycle is None:
            return None
        return self._store.save(decay.apply_decay(lifecycle, now=at))

    def sweep_decay(self, scope: Optional[MemoryScope] = None, at: Optional[datetime] = None) -> list[MemoryLifecycle]:
        """Apply decay across every lifecycle record in scope — the
        periodic maintenance pass. Returns the updated records."""
        updated = []
        for lifecycle in self._store.list_all(scope=scope):
            updated.append(self._store.save(decay.apply_decay(lifecycle, now=at)))
        return updated

    def run_hygiene_sweep(self, scope: Optional[MemoryScope] = None, at: Optional[datetime] = None) -> list[MemoryLifecycle]:
        """The memory-hygiene pass: decay every lifecycle record in scope,
        then archive (never delete) any that came out fully stale
        (EXPIRED) and were never once recalled (access_count == 0) —
        "low-value + old + never recalled -> decay -> archive", not
        immediate deletion. A memory that was accessed even once is left
        merely EXPIRED/DECAYED, not archived — some use is still a
        signal worth keeping active for."""
        archived = []
        for lifecycle in self.sweep_decay(scope=scope, at=at):
            if lifecycle.status == MemoryStatus.EXPIRED and lifecycle.access_count == 0:
                archived.append(self._store.save(archival.archive(lifecycle, reason="decayed_unused", at=at)))
            else:
                archived.append(lifecycle)
        return archived

    def archive_superseded(self, memory: Memory, at: Optional[datetime] = None) -> Optional[MemoryLifecycle]:
        """Memory superseded -> archive."""
        if memory.superseded_by is None:
            return None
        lifecycle = self._store.get(memory.memory_id, scope=memory.scope) or MemoryLifecycle(
            memory_id=memory.memory_id, scope=memory.scope
        )
        archived = archival.archive(lifecycle, reason=f"superseded_by:{memory.superseded_by}", at=at)
        return self._store.save(archived)

    def forget(
        self,
        memory_id: str,
        scope: Optional[MemoryScope] = None,
        reason: str = forgetting.DEFAULT_FORGET_REASON,
        at: Optional[datetime] = None,
    ) -> MemoryLifecycle:
        """Memory explicitly deleted -> forget. Call cascade_provenance
        separately to clean up dangling references elsewhere."""
        lifecycle = self._store.get(memory_id, scope=scope) or MemoryLifecycle(memory_id=memory_id, scope=scope)
        return self._store.save(forgetting.forget(lifecycle, reason=reason, at=at))

    def cascade_provenance(
        self,
        memory_id: str,
        documents: Iterable[KnowledgeDocument] = (),
        memories: Iterable[Memory] = (),
    ) -> tuple[list[KnowledgeDocument], list[Memory]]:
        """Given a forgotten memory's id, return cleaned copies of any
        documents/memories that referenced it — the caller persists
        these via DocumentStore/KnowledgeStore."""
        return (
            forgetting.cascade_forget_documents(memory_id, documents),
            forgetting.cascade_forget_memories(memory_id, memories),
        )
