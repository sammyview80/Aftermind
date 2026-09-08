from dataclasses import replace
from datetime import datetime, timezone
from typing import Iterable, Optional

from domain.enums.memory_status import MemoryStatus
from domain.models.knowledge_document import KnowledgeDocument
from domain.models.memory import Memory
from domain.models.memory_lifecycle import MemoryLifecycle

DEFAULT_FORGET_REASON = "explicit_delete"


def forget(
    lifecycle: MemoryLifecycle, reason: str = DEFAULT_FORGET_REASON, at: Optional[datetime] = None
) -> MemoryLifecycle:
    """Explicit, terminal deletion — the only lifecycle action that's not
    meant to be reversed by reinforcement. Content isn't touched here;
    callers should also remove/mask the underlying Memory content
    depending on their retention policy. This only marks the lifecycle
    record itself forgotten; cascade_forget_* below clean up the
    dangling references that would otherwise point at it.
    """
    now = at or datetime.now(timezone.utc)
    return replace(
        lifecycle,
        status=MemoryStatus.FORGOTTEN,
        metadata={**lifecycle.metadata, "forgotten_reason": reason, "forgotten_at": now.isoformat()},
        updated_at=now,
    )


def cascade_forget_documents(
    memory_id: str, documents: Iterable[KnowledgeDocument]
) -> list[KnowledgeDocument]:
    """Strip a forgotten memory's id out of every document's
    source_memory_ids — the document's consolidated content stays, only
    the dangling provenance pointer is removed."""
    return [
        replace(doc, source_memory_ids=tuple(mid for mid in doc.source_memory_ids if mid != memory_id))
        if memory_id in doc.source_memory_ids
        else doc
        for doc in documents
    ]


def cascade_forget_memories(memory_id: str, memories: Iterable[Memory]) -> list[Memory]:
    """Clear any `superseded_by` pointer that targets a now-forgotten
    memory, so nothing links forward to a memory that no longer exists."""
    return [replace(m, superseded_by=None) if m.superseded_by == memory_id else m for m in memories]
