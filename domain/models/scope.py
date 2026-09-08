from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Iterable, Mapping, Optional

from domain.policies.scope_policy import DEFAULT_EXECUTION_LEVELS, DEFAULT_HIERARCHY


@dataclass(frozen=True)
class MemoryScope:
    """Identifies who a memory belongs to and where it applies.

    Levels are an open, arbitrary key/value map — not fixed dataclass
    fields — so new scope dimensions (team, branch, environment, ...) plug
    in without modifying this class. `ScopeLevel` names the standard ones;
    `DEFAULT_HIERARCHY`/`DEFAULT_EXECUTION_LEVELS` (domain.policies.scope_policy)
    give sane defaults out of the box, but every method accepts its own
    override for callers with a different shape.

    `agent_id` (when present) is a stable *logical* agent identity chosen
    by the caller (e.g. "coder") — never a framework-native session or
    profile id; those map onto it via ExternalIdentity in the adapters, so
    the same agent_id can be shared across Hermes, Claude Code, Codex,
    LangGraph, etc. without coupling this model to any of them.

    Model/provider (e.g. "claude-opus") is deliberately excluded — that is
    event provenance, not memory ownership.
    """

    levels: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "levels", MappingProxyType(dict(self.levels)))

    @classmethod
    def of(cls, **levels: Optional[str]) -> "MemoryScope":
        """Build a scope from keyword levels, dropping unset (None) ones."""
        return cls(levels={k: v for k, v in levels.items() if v is not None})

    def get(self, level: str) -> Optional[str]:
        return self.levels.get(level)

    def with_levels(self, **overrides: Optional[str]) -> "MemoryScope":
        """Return a copy with the given levels set/overridden (None removes)."""
        merged = dict(self.levels)
        for k, v in overrides.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        return replace(self, levels=merged)

    def key(self, hierarchy: Iterable[str] = DEFAULT_HIERARCHY) -> str:
        """Full identity key over `hierarchy`, unset levels as wildcard."""
        return ":".join(self.levels.get(level, "*") for level in hierarchy)

    def key_at(self, level: str, hierarchy: Iterable[str] = DEFAULT_HIERARCHY) -> str:
        """Key truncated to `hierarchy` up to and including `level`.

        Used to bucket/query memories by ownership scope, e.g. a
        REPOSITORY-level memory should be found by any agent/task/run
        within that repository. Raises if a required level is unset.
        """
        hierarchy = tuple(hierarchy)
        if level not in hierarchy:
            raise ValueError(f"level={level!r} not in hierarchy={hierarchy!r}")
        prefix = hierarchy[: hierarchy.index(level) + 1]
        missing = [f for f in prefix if f not in self.levels]
        if missing:
            raise ValueError(f"scope missing required level(s) for key_at({level!r}): {missing}")
        return ":".join(self.levels[f] for f in prefix)

    def is_execution_scope(self, execution_levels: frozenset[str] = DEFAULT_EXECUTION_LEVELS) -> bool:
        """True if this scope carries any transient execution-identity level."""
        return any(level in self.levels for level in execution_levels)

    def stable(self, execution_levels: frozenset[str] = DEFAULT_EXECUTION_LEVELS) -> "MemoryScope":
        """Return a copy with transient execution-identity levels stripped."""
        return replace(self, levels={k: v for k, v in self.levels.items() if k not in execution_levels})
