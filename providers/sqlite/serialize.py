import json
from datetime import datetime, timezone
from typing import Optional

from domain.models.scope import MemoryScope


def scope_key(scope: Optional[MemoryScope]) -> str:
    return scope.key() if scope is not None else "*"


def dump_scope_levels(scope: Optional[MemoryScope]) -> str:
    return json.dumps(dict(scope.levels)) if scope is not None else "{}"


def load_scope(scope_levels_json: str) -> Optional[MemoryScope]:
    levels = json.loads(scope_levels_json)
    return MemoryScope.of(**levels) if levels else None


def dump_json(value) -> str:
    return json.dumps(value)


def load_json(value: str):
    return json.loads(value)


def dump_dt(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def load_dt(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value) if value else None


def load_dt_required(value: str) -> datetime:
    return datetime.fromisoformat(value)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
