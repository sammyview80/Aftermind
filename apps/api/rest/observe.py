from typing import Optional

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from apps.api.deps import get_service
from apps.api.rest.schemas import ScopeRequest
from core.facade import AftermindService
from core.observability import trace
from domain.enums.event_type import EventType
from domain.models.event import Event
from domain.models.experience import Experience

router = APIRouter()


class ObserveRequest(BaseModel):
    scope: ScopeRequest = ScopeRequest()
    input: str = ""
    output: str = ""
    event_type: str = EventType.AGENT_MESSAGE.value


class ObserveSync(BaseModel):
    """Per-store outcome of this observe, straight from its trace.
    `ok` = written; `pending` = SQLite committed, secondary store
    failed, a durable retry job exists; `skipped` = nothing to do."""

    sqlite_write: str
    neo4j_sync: str
    openknowledge_sync: str


class ObserveResponse(BaseModel):
    created: bool
    memory_id: Optional[str] = None
    content: Optional[str] = None
    memory_ids: list[str] = []
    observe_id: str
    admission: Optional[str] = None  # "llm" | "rules" | "rejected:<reason>"
    reconciliation_action: Optional[str] = None
    sync: ObserveSync


@router.post("/observe", response_model=ObserveResponse)
def observe(
    request: ObserveRequest, response: Response, service: AftermindService = Depends(get_service)
) -> ObserveResponse:
    experience = Experience(
        scope=request.scope.to_domain(),
        events=[Event(event_type=EventType(request.event_type))],
        input=request.input,
        output=request.output,
    )
    # Open the trace here so the facade joins it and we can read the
    # per-store outcomes back for the response.
    with service.tracer.begin("observe", scope=experience.scope.key() if experience.scope else None) as t:
        memory = service.observe(experience)

    response.headers["X-Aftermind-Trace-Id"] = t.trace_id
    sync = ObserveSync(
        sqlite_write=t.fields.get("sqlite_write", trace.SKIPPED),
        neo4j_sync=t.fields.get("neo4j_sync", trace.SKIPPED),
        openknowledge_sync=t.fields.get("openknowledge_sync", trace.SKIPPED),
    )
    if memory is None:
        return ObserveResponse(
            created=False,
            observe_id=t.trace_id,
            admission=t.fields.get("admission"),
            reconciliation_action=t.fields.get("reconciliation_action"),
            sync=sync,
        )
    return ObserveResponse(
        created=True,
        memory_id=memory.memory_id,
        content=memory.content,
        memory_ids=list(t.fields.get("memory_ids", [memory.memory_id])),
        observe_id=t.trace_id,
        admission=t.fields.get("admission"),
        reconciliation_action=t.fields.get("reconciliation_action"),
        sync=sync,
    )
