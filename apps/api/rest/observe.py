from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.deps import get_service
from apps.api.rest.schemas import ScopeRequest
from core.facade import AftermindService
from domain.enums.event_type import EventType
from domain.models.event import Event
from domain.models.experience import Experience

router = APIRouter()


class ObserveRequest(BaseModel):
    scope: ScopeRequest = ScopeRequest()
    input: str = ""
    output: str = ""
    event_type: str = EventType.AGENT_MESSAGE.value


class ObserveResponse(BaseModel):
    created: bool
    memory_id: Optional[str] = None
    content: Optional[str] = None


@router.post("/observe", response_model=ObserveResponse)
def observe(request: ObserveRequest, service: AftermindService = Depends(get_service)) -> ObserveResponse:
    experience = Experience(
        scope=request.scope.to_domain(),
        events=[Event(event_type=EventType(request.event_type))],
        input=request.input,
        output=request.output,
    )
    memory = service.observe(experience)
    if memory is None:
        return ObserveResponse(created=False)
    return ObserveResponse(created=True, memory_id=memory.memory_id, content=memory.content)
