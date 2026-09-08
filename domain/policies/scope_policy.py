from domain.enums.scope_level import ScopeLevel

# Default ordering, broadest -> narrowest. This is a *default*, not a
# contract: callers can supply their own hierarchy to key()/key_at()
# without touching this file, so adding a new level (e.g. "team_id",
# "branch_id") never requires a code change here.
DEFAULT_HIERARCHY: tuple[str, ...] = (
    ScopeLevel.TENANT,
    ScopeLevel.WORKSPACE,
    ScopeLevel.PROJECT,
    ScopeLevel.REPOSITORY,
    ScopeLevel.USER,
    ScopeLevel.AGENT,
    ScopeLevel.TASK,
    ScopeLevel.CONVERSATION,
    ScopeLevel.SESSION,
    ScopeLevel.RUN,
)

# Execution-identity levels are transient (per-run); everything else is
# stable ownership. Used only as a default classifier — callers may pass
# their own set.
DEFAULT_EXECUTION_LEVELS: frozenset[str] = frozenset(
    {
        ScopeLevel.CONVERSATION,
        ScopeLevel.SESSION,
        ScopeLevel.RUN,
        ScopeLevel.PARENT_RUN,
    }
)
