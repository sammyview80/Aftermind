from typing import Optional, Protocol

from domain.models.preference import Preference
from domain.models.scope import MemoryScope


class PreferenceStore(Protocol):
    """Persistence for the learned preference profile.

    `save` is an upsert keyed by `preference_id` — unlike checkpoints,
    a preference row is mutated in place while evidence accumulates
    for the same value, so repeated observations don't create N rows.
    """

    def save(self, preference: Preference) -> Preference: ...

    def latest_by_dimension(self, scope: Optional[MemoryScope], dimension: str) -> Optional[Preference]: ...

    def list_active(self, scope: Optional[MemoryScope]) -> tuple[Preference, ...]: ...
