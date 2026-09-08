from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.deps import get_service, get_sync_worker
from apps.api.rest.schemas import ScopeRequest
from core.facade import AftermindService
from core.sync.worker import SyncWorker
from domain.enums.memory_status import MemoryStatus
from domain.enums.sync_job_status import SyncJobStatus

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


class SyncJobView(BaseModel):
    job_id: str
    kind: str
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: str
    last_error: Optional[str] = None
    trace_id: Optional[str] = None
    payload: dict
    created_at: str


class SyncStatusResponse(BaseModel):
    mode: str
    durable: bool
    worker_running: bool
    counts: dict[str, int]
    jobs: list[SyncJobView]


def _view(job) -> SyncJobView:
    return SyncJobView(
        job_id=job.job_id,
        kind=job.kind.value,
        status=job.status.value,
        attempts=job.attempts,
        max_attempts=job.max_attempts,
        next_attempt_at=job.next_attempt_at.isoformat(),
        last_error=job.last_error,
        trace_id=job.trace_id,
        payload=dict(job.payload),
        created_at=job.created_at.isoformat(),
    )


@router.get("/maintenance/sync", response_model=SyncStatusResponse)
def sync_status(
    status: Optional[str] = None,
    limit: int = 50,
    service: AftermindService = Depends(get_service),
    worker: SyncWorker = Depends(get_sync_worker),
) -> SyncStatusResponse:
    """Outbox backlog: counts per status plus the most recent jobs
    (filter with ?status=pending|running|done|dead). A non-empty `dead`
    bucket means retries were exhausted and needs a look."""
    store = worker._job_store
    wanted = SyncJobStatus(status) if status else None
    return SyncStatusResponse(
        mode=service.sync.mode,
        durable=service.sync.durable,
        worker_running=worker.running,
        counts=store.counts(),
        jobs=[_view(j) for j in store.list_jobs(status=wanted, limit=limit)],
    )


class SyncRunResponse(BaseModel):
    processed: dict[str, int]


@router.post("/maintenance/sync/run", response_model=SyncRunResponse)
def sync_run(worker: SyncWorker = Depends(get_sync_worker)) -> SyncRunResponse:
    """Drain every currently-due job now (instead of waiting for the
    worker's next poll). Useful right after Neo4j/OpenKnowledge comes back."""
    return SyncRunResponse(processed=worker.drain())


class SyncRetryRequest(BaseModel):
    job_id: Optional[str] = None  # None = every dead job


class SyncRetryResponse(BaseModel):
    requeued: int


@router.post("/maintenance/sync/retry", response_model=SyncRetryResponse)
def sync_retry(request: SyncRetryRequest, worker: SyncWorker = Depends(get_sync_worker)) -> SyncRetryResponse:
    """Requeue dead jobs (attempt counter reset) so the worker tries again."""
    return SyncRetryResponse(requeued=worker.retry_dead(request.job_id))
