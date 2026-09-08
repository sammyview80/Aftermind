from typing import Optional

from pydantic import BaseModel

from domain.models.scope import MemoryScope


class ScopeRequest(BaseModel):
    """Scope levels as a flat dict, e.g. {"tenant_id": "t1", "project_id": "aftermind"}."""

    levels: dict[str, str] = {}

    def to_domain(self) -> Optional[MemoryScope]:
        return MemoryScope.of(**self.levels) if self.levels else None


class MemorySummary(BaseModel):
    memory_id: str
    content: str
    memory_type: str
    confidence: float
