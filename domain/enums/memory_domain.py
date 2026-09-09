from enum import Enum


class MemoryDomain(str, Enum):
    """What *kind* of durable fact a memory is, orthogonal to scope
    (which says *where* it applies). This is what keeps company policy,
    project architecture, and personal style from contaminating each
    other during recall — a repository-scoped memory can still be
    ORGANIZATION-domain (a policy that happens to have been stated while
    working in this repo), and recall/domain routing (see
    core/recall/domain_router.py) decides which domains are relevant to
    a given query, independent of the deterministic scope filter.
    """

    SESSION = "session"  # transient: current blocker, in-progress state
    PROJECT = "project"  # durable technical/architectural fact
    USER = "user"  # a fact about the user (not response style — that's core/preferences)
    ORGANIZATION = "organization"  # company-wide policy/process
