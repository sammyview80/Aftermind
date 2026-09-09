from typing import Optional, Protocol

from domain.models.scope import MemoryScope


class PreferenceEvidenceStore(Protocol):
    """Durable buffer of raw text pending LLM preference reconciliation.

    Separate from `PreferenceStore`: this holds unreconciled evidence
    (one row per observed turn), cleared once the reconciler consumes
    it, whereas `PreferenceStore` holds the reconciled, stable profile.
    """

    def append(self, scope: Optional[MemoryScope], text: str) -> None: ...

    def recent(self, scope: Optional[MemoryScope]) -> tuple[str, ...]: ...

    def clear(self, scope: Optional[MemoryScope]) -> None: ...
