from typing import Optional, Protocol

from domain.models.knowledge_document import KnowledgeDocument
from domain.models.scope import MemoryScope


class DocumentStore(Protocol):
    """Persistence for KnowledgeDocument — consolidated, human-readable
    knowledge. Backed by OpenKnowledge in production, a local markdown
    directory in dev, an in-memory dict in tests.

    Deliberately not named "knowledge_store" — that name is already
    domain.interfaces.knowledge_store.KnowledgeStore, which persists
    atomic StoredMemory (Postgres). This is a different tier: durable,
    consolidated documents, not every memory.
    """

    def get(self, slug: str, scope: Optional[MemoryScope] = None) -> Optional[KnowledgeDocument]: ...

    def save(self, document: KnowledgeDocument) -> KnowledgeDocument: ...

    def search(self, query: str, scope: Optional[MemoryScope] = None, limit: int = 5) -> list[KnowledgeDocument]: ...
