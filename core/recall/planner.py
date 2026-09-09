from dataclasses import dataclass, field
from typing import Optional

from core.recall.domain_router import DomainRouter
from domain.enums.memory_domain import MemoryDomain
from domain.enums.memory_type import MemoryType
from domain.models.checkpoint import Checkpoint
from domain.models.recall_query import RecallQuery
from domain.models.scope import MemoryScope

_STOPWORDS = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "for", "with", "this", "that", "from", "into", "onto",
        "is", "are", "was", "were", "be", "to", "of", "on", "in", "at", "it", "as", "by", "we", "you",
    }
)


@dataclass(frozen=True)
class RecallPlan:
    """What to search, decided before any retrieval happens."""

    scope: Optional[MemoryScope]
    fetch_checkpoint: bool
    search_terms: tuple[str, ...]
    memory_types: tuple[MemoryType, ...]
    entity_seeds: tuple[str, ...]
    limit: int
    domains: tuple[MemoryDomain, ...] = field(default_factory=tuple)
    include_preferences: bool = True
    include_graph: bool = True
    include_knowledge: bool = True


def _keywords(text: str, min_length: int = 4) -> list[str]:
    seen: dict[str, None] = {}
    for word in text.split():
        cleaned = word.strip(".,!?:;\"'()").lower()
        if len(cleaned) >= min_length and cleaned not in _STOPWORDS:
            seen.setdefault(cleaned, None)
    return list(seen)


class RecallPlanner:
    """Decides what to search: the latest checkpoint, which memory types
    (episodic task history, semantic project decisions), and which
    entities to look up in the graph.

    Checkpoint content is weighted first — its goal/current/blockers/next
    describe exactly what "continue" means for this scope, so search
    terms are drawn from it before the raw query text.
    """

    def __init__(self, router: Optional[DomainRouter] = None) -> None:
        self._router = router or DomainRouter()

    def plan(self, query: RecallQuery, checkpoint: Optional[Checkpoint]) -> RecallPlan:
        routing = self._router.route(query, checkpoint)
        search_terms: list[str] = []
        entity_seeds: list[str] = []

        if checkpoint is not None and routing.include_checkpoint:
            for text in (checkpoint.goal, checkpoint.current, *checkpoint.blockers, *checkpoint.next_steps):
                if text:
                    search_terms.append(text)
                    entity_seeds.extend(_keywords(text))

        if query.text:
            search_terms.append(query.text)
            entity_seeds.extend(_keywords(query.text))

        memory_types = query.memory_types or (MemoryType.EPISODIC, MemoryType.SEMANTIC)

        return RecallPlan(
            scope=query.scope,
            fetch_checkpoint=routing.include_checkpoint,
            search_terms=tuple(dict.fromkeys(search_terms)),
            memory_types=tuple(memory_types),
            entity_seeds=tuple(dict.fromkeys(entity_seeds)),
            limit=query.limit,
            domains=routing.domains,
            include_preferences=routing.include_preferences,
            include_graph=routing.include_graph,
            include_knowledge=routing.include_knowledge,
        )
