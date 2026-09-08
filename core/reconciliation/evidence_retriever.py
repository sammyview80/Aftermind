from domain.interfaces.knowledge_store import KnowledgeStore
from domain.models.candidate import Candidate
from domain.models.memory import Memory

DEFAULT_EVIDENCE_LIMIT = 5


class EvidenceRetriever:
    """Searches existing memory for anything relevant to a candidate,
    before the reconciler decides what to do with it."""

    def __init__(self, knowledge_store: KnowledgeStore, limit: int = DEFAULT_EVIDENCE_LIMIT) -> None:
        self._store = knowledge_store
        self._limit = limit

    def retrieve(self, candidate: Candidate) -> list[Memory]:
        return self._store.search(candidate.content, scope=candidate.scope, limit=self._limit)
