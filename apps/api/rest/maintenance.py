from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.deps import get_service
from apps.api.rest.schemas import ScopeRequest
from core.facade import AftermindService
from domain.enums.memory_status import MemoryStatus

router = APIRouter()


class MaintenanceSweepRequest(BaseModel):
    scope: ScopeRequest = ScopeRequest()


class MaintenanceSweepResponse(BaseModel):
    swept: int
    archived: int


@router.post("/maintenance/sweep", response_model=MaintenanceSweepResponse)
def sweep(request: MaintenanceSweepRequest, service: AftermindService = Depends(get_service)) -> MaintenanceSweepResponse:
    """Memory hygiene pass: decay stale lifecycle records in scope and
    archive the ones that are fully stale and were never recalled.
    Never deletes content — call periodically (cron), not per-request."""
    results = service.run_lifecycle_maintenance(scope=request.scope.to_domain())
    archived = sum(1 for r in results if r.status == MemoryStatus.ARCHIVED)
    return MaintenanceSweepResponse(swept=len(results), archived=archived)
