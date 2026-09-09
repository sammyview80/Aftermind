from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping, Optional
from uuid import uuid4

from domain.enums.preference_source import PreferenceSource
from domain.models.scope import MemoryScope


@dataclass(frozen=True)
class Preference:
    """A learned, evidence-weighted user/agent preference — e.g.
    dimension="response_style", value={"verbosity": "short"}.

    Distinct from `Memory`: preferences are a reconciled *profile* (one
    active row per dimension per scope), not a growing log of facts.
    `evidence_count`/`confidence` grow as the same value keeps being
    observed; a contradicting observation supersedes the row (same
    version-chain pattern as `Memory.superseded_by`) rather than
    overwriting it, so the profile's history is inspectable.
    """

    preference_id: str = field(default_factory=lambda: str(uuid4()))
    scope: Optional[MemoryScope] = None
    dimension: str = ""
    value: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    confidence: float = 0.0
    evidence_count: int = 0
    source: PreferenceSource = PreferenceSource.INFERRED
    version: int = 1
    superseded_by: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", MappingProxyType(dict(self.value)))
