from typing import Optional, Protocol

from domain.models.experience import Experience


class EpisodeStore(Protocol):
    """Persistence for raw Experiences, kept independent of whether any
    Candidate extracted from them was ever accepted as a Memory."""

    def save(self, experience: Experience) -> Experience: ...

    def get(self, experience_id: str) -> Optional[Experience]: ...
