from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.enums.event_type import EventType
from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class Event:
    """Normalized event, framework-neutral.

    Every source framework (Hermes, Claude Code, Codex, LangGraph, ...)
    maps its own native event shape onto this one before it enters the
    memory pipeline. Nothing downstream of this model should need to know
    which framework an event came from beyond the `source` label.
    """

    event_id: str = field(default_factory=lambda: str(uuid4()))
    event_type: EventType = EventType.USER_MESSAGE
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    scope: Optional[MemoryScope] = None
    payload: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    source: str = ""  # framework/integration name, e.g. "langgraph"
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
