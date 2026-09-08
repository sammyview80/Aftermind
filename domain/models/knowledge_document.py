from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class KnowledgeSection:
    """One heading + body within a KnowledgeDocument."""

    heading: str
    body: str


@dataclass(frozen=True)
class KnowledgeDocument:
    """Durable, human-readable knowledge — the consolidated end state,
    distinct from atomic StoredMemory (Postgres) and entities/
    relationships (Graphiti/Neo4j). Meant to be read by a person, not
    just an agent: a project architecture doc, a decisions log, not a
    dump of every memory.

    `source_memory_ids` traces which memories were consolidated into
    this document, without this document being one-to-one with any of
    them — many memories fold into one section over time.
    """

    document_id: str = field(default_factory=lambda: str(uuid4()))
    scope: Optional[MemoryScope] = None
    slug: str = ""
    title: str = ""
    sections: tuple[KnowledgeSection, ...] = field(default_factory=tuple)
    source_memory_ids: tuple[str, ...] = field(default_factory=tuple)
    version: int = 1
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", tuple(self.sections))
        object.__setattr__(self, "source_memory_ids", tuple(self.source_memory_ids))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_markdown(self) -> str:
        parts = [f"# {self.title}"]
        for section in self.sections:
            parts.append(f"## {section.heading}\n\n{section.body}")
        return "\n\n".join(parts)
