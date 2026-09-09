import re
from dataclasses import dataclass
from typing import Optional

from domain.enums.memory_domain import MemoryDomain
from domain.models.checkpoint import Checkpoint
from domain.models.recall_query import RecallQuery

# Deterministic keyword routing, same reasoning as
# core/formation/domain_classifier.py: this decides *which* domains are
# worth searching, not a security boundary (scope filtering remains
# that) — a wrong guess here costs recall quality, not correctness, so
# a cheap heuristic beats an LLM call on every recall.

_CONTINUATION_PATTERNS = (
    re.compile(r"\bcontinue\b", re.IGNORECASE),
    re.compile(r"\bwhere were we\b", re.IGNORECASE),
    re.compile(r"\bwhat were we\b", re.IGNORECASE),
    re.compile(r"\bkeep going\b", re.IGNORECASE),
    re.compile(r"\bresume\b", re.IGNORECASE),
    re.compile(r"\bwhat('s| is) next\b", re.IGNORECASE),
)

_ORGANIZATION_PATTERNS = (
    re.compile(r"\bcompany\b", re.IGNORECASE),
    re.compile(r"\borg(?:anization)?[- ]wide\b", re.IGNORECASE),
    re.compile(r"\bpolicy\b", re.IGNORECASE),
    re.compile(r"\bapproval process\b", re.IGNORECASE),
    re.compile(r"\bcompliance\b", re.IGNORECASE),
    re.compile(r"\bexpense\b", re.IGNORECASE),
    re.compile(r"\bHR\b"),
)

_USER_PATTERNS = (
    re.compile(r"\bmy (timezone|role|title|team|preference)\b", re.IGNORECASE),
    re.compile(r"\bwho am i\b", re.IGNORECASE),
    re.compile(r"\babout me\b", re.IGNORECASE),
)


def _matches(text: str, patterns: tuple[re.Pattern, ...]) -> bool:
    return any(p.search(text) for p in patterns)


@dataclass(frozen=True)
class RecallRouting:
    """What a recall should search, decided from the query text alone
    (before any retrieval happens) — which memory domains are relevant,
    and whether the checkpoint/preference profile/graph/OpenKnowledge
    sources are worth consulting at all for this query."""

    domains: tuple[MemoryDomain, ...]
    include_checkpoint: bool
    include_preferences: bool
    include_graph: bool
    include_knowledge: bool


class DomainRouter:
    """Decides which memory domains (SESSION/PROJECT/USER/ORGANIZATION)
    a recall query is actually asking about, independent of scope.
    Preferences (response style) are always considered — they're cheap,
    small, and near-universally relevant — but factual recall domains
    are targeted so an "our company's expense policy" question doesn't
    surface unrelated session blockers, and "continue what we were
    doing" doesn't drag in every organization-wide policy."""

    def route(self, query: RecallQuery, checkpoint: Optional[Checkpoint] = None) -> RecallRouting:
        text = (query.text or "").strip()
        is_continuation = not text or _matches(text, _CONTINUATION_PATTERNS)
        is_org_query = _matches(text, _ORGANIZATION_PATTERNS)
        is_user_query = _matches(text, _USER_PATTERNS)

        domains: set[MemoryDomain] = set()
        if is_continuation:
            domains.add(MemoryDomain.SESSION)
            domains.add(MemoryDomain.PROJECT)
        if is_org_query:
            domains.add(MemoryDomain.ORGANIZATION)
            domains.add(MemoryDomain.PROJECT)
        if is_user_query:
            domains.add(MemoryDomain.USER)
        if not domains:
            # A real query that matched none of the above — default to
            # the two domains that cover most day-to-day work rather
            # than searching nothing.
            domains.update({MemoryDomain.PROJECT, MemoryDomain.SESSION})

        return RecallRouting(
            domains=tuple(sorted(domains, key=lambda d: d.value)),
            include_checkpoint=is_continuation or checkpoint is not None,
            include_preferences=True,
            include_graph=True,
            include_knowledge=is_org_query or bool(text),
        )
