import re

from domain.enums.memory_domain import MemoryDomain

# Deterministic keyword classification, not an LLM call — this runs on
# every candidate, same reasoning as core/preferences/signals.py: cheap
# and explainable beats an extra model call for a coarse 4-way split.
# Checked most-specific-scope-first (ORGANIZATION, then SESSION, then
# USER) so a session blocker mentioning "the company" isn't misfiled as
# organization policy just because a company noun appears; PROJECT is
# the default for everything else (architecture/tech facts).

_ORGANIZATION_PATTERNS = (
    re.compile(r"\bcompany(?:'s)? (policy|process|standard|requires?)\b", re.IGNORECASE),
    re.compile(r"\borg(?:anization)?[- ]wide\b", re.IGNORECASE),
    re.compile(r"\brequires? (manager |admin )?approval\b", re.IGNORECASE),
    re.compile(r"\bcompliance requirement\b", re.IGNORECASE),
    re.compile(r"\bHR (policy|process)\b", re.IGNORECASE),
)

_SESSION_PATTERNS = (
    re.compile(r"\bcurrent(ly)? blocked?( on)?\b", re.IGNORECASE),
    re.compile(r"\bcurrent blocker\b", re.IGNORECASE),
    re.compile(r"\bright now\b", re.IGNORECASE),
    re.compile(r"\bin progress\b", re.IGNORECASE),
    re.compile(r"\bwaiting on\b", re.IGNORECASE),
)

_USER_PATTERNS = (
    re.compile(r"\bthe user('s)?\b", re.IGNORECASE),
    re.compile(r"\byou (are|work|live)\b", re.IGNORECASE),
    re.compile(r"\bmy (timezone|role|title|team)\b", re.IGNORECASE),
)


def classify_domain(text: str) -> MemoryDomain:
    """Best-effort domain for one candidate's content. A wrong guess here
    is not catastrophic — it's a coarse routing hint for recall (see
    core/recall/domain_router.py), not a security boundary; scope
    filtering remains the deterministic ownership check."""
    if not text:
        return MemoryDomain.PROJECT
    if any(p.search(text) for p in _ORGANIZATION_PATTERNS):
        return MemoryDomain.ORGANIZATION
    if any(p.search(text) for p in _SESSION_PATTERNS):
        return MemoryDomain.SESSION
    if any(p.search(text) for p in _USER_PATTERNS):
        return MemoryDomain.USER
    return MemoryDomain.PROJECT
