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
        # Stored memories carry stabilized (execution-scope-stripped)
        # scope — search with the same stabilized scope so evidence from
        # earlier sessions is actually found, not just this run's.
        scope = candidate.scope.stable() if candidate.scope else None
        return self._store.search(candidate.content, scope=scope, limit=self._limit)
