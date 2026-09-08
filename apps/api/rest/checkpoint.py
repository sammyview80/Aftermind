from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.deps import get_service
from apps.api.rest.schemas import ScopeRequest
from core.facade import AftermindService

router = APIRouter()


class CheckpointRequest(BaseModel):
    scope: ScopeRequest = ScopeRequest()
    goal: str = ""
    current: str = ""
    completed: list[str] = []
    blockers: list[str] = []
    next_steps: list[str] = []
    memory_ids: list[str] = []
    reason: str = "manual"


class LatestCheckpointRequest(BaseModel):
    scope: ScopeRequest = ScopeRequest()


class CheckpointResponse(BaseModel):
    found: bool
    checkpoint_id: Optional[str] = None
    version: Optional[int] = None
    goal: Optional[str] = None
    current: Optional[str] = None
    completed: list[str] = []
    blockers: list[str] = []
    next_steps: list[str] = []


def _to_response(checkpoint) -> CheckpointResponse:
    return CheckpointResponse(
        found=True,
        checkpoint_id=checkpoint.checkpoint_id,
        version=checkpoint.version,
        goal=checkpoint.goal,
        current=checkpoint.current,
        completed=list(checkpoint.completed),
        blockers=list(checkpoint.blockers),
        next_steps=list(checkpoint.next_steps),
    )


@router.post("/checkpoint", response_model=CheckpointResponse)
def create_checkpoint(
    request: CheckpointRequest, service: AftermindService = Depends(get_service)
) -> CheckpointResponse:
    checkpoint = service.checkpoint(
        scope=request.scope.to_domain(),
        goal=request.goal,
        current=request.current,
        completed=request.completed,
        blockers=request.blockers,
        next_steps=request.next_steps,
        memory_ids=request.memory_ids,
        reason=request.reason,
    )
    return _to_response(checkpoint)


@router.post("/checkpoint/latest", response_model=CheckpointResponse)
def latest_checkpoint(
    request: LatestCheckpointRequest, service: AftermindService = Depends(get_service)
) -> CheckpointResponse:
    checkpoint = service.latest_checkpoint(scope=request.scope.to_domain())
    if checkpoint is None:
        return CheckpointResponse(found=False)
    return _to_response(checkpoint)
