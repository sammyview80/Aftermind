from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.enums.experience_outcome import ExperienceOutcome
from domain.models.event import Event
from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class Experience:
    """A coherent unit assembled from one or more raw events.

    Experience only assembles what happened — goal, actions taken, result,
    outcome. It does not judge whether any of that is worth remembering;
    that decision belongs to candidate extraction (domain/models/candidate.py)
    and the memory evaluator downstream.
    """

    experience_id: str = field(default_factory=lambda: str(uuid4()))
    scope: Optional[MemoryScope] = None
    events: tuple[Event, ...] = field(default_factory=tuple)
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    input: str = ""
    output: str = ""
    outcome: ExperienceOutcome = ExperienceOutcome.UNKNOWN
    success: Optional[bool] = None
    metadata: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
