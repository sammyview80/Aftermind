from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from apps.api.deps import get_settings, get_trace_sink
from core.observability.trace import InMemoryTraceSink

router = APIRouter()


@router.get("/traces")
def traces(
    limit: int = 50, operation: Optional[str] = None, sink: InMemoryTraceSink = Depends(get_trace_sink)
) -> dict:
    """Most recent operation traces (newest first) from this process's
    ring buffer — the same records that go to the `aftermind.trace` log.
    Filter with ?operation=observe|recall|sync_job|checkpoint."""
    return {"traces": [t.to_dict() for t in sink.recent(limit=limit, operation=operation)]}


@router.get("/traces/{trace_id}")
def trace_by_id(trace_id: str, sink: InMemoryTraceSink = Depends(get_trace_sink)) -> dict:
    found = sink.get(trace_id)
    if found is None:
        raise HTTPException(status_code=404, detail="trace not found (buffer is bounded; check logs)")
    # Sync jobs retried later run as child traces linked by parent_trace_id.
    children = [t.to_dict() for t in sink.recent(limit=1000) if t.parent_trace_id == trace_id]
    return {**found.to_dict(), "children": children}


@router.get("/config")
def config() -> dict:
    """Effective runtime configuration, secrets redacted."""
    return get_settings().redacted()
