from fastapi import APIRouter, Depends, Response

from apps.api.deps import get_service, get_settings, get_sqlite_client, get_sync_worker
from domain.enums.sync_job_status import SyncJobStatus

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: the process is up. Cheap, no store access."""
    return {"status": "ok"}


@router.get("/health/ready")
def ready(response: Response, service=Depends(get_service), worker=Depends(get_sync_worker)) -> dict:
    """Readiness: can this instance serve memory operations? SQLite must
    be reachable (canonical). Secondary stores and the sync backlog are
    reported but do not fail readiness — that is the point of the
    outbox: Neo4j/OpenKnowledge being down degrades, it doesn't stop.
    `dead` jobs (retries exhausted) flip status to `degraded`."""
    settings = get_settings()
    checks: dict = {"sqlite": "ok"}
    try:
        checks["sqlite"] = "ok" if get_sqlite_client().integrity_check() else "corrupt"
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        checks["sqlite"] = f"error: {type(exc).__name__}"

    checks["graph_backend"] = settings.graph_backend
    checks["document_backend"] = settings.document_backend
    checks["sync_mode"] = settings.sync_mode
    checks["sync_worker"] = "running" if worker.running else "stopped"

    counts: dict[str, int] = {}
    if service.sync.durable:
        counts = worker._job_store.counts()
    checks["sync_jobs"] = counts

    status = "ok"
    if checks["sqlite"] != "ok":
        status = "unavailable"
        response.status_code = 503
    elif counts.get(SyncJobStatus.DEAD.value, 0) > 0:
        status = "degraded"

    return {"status": status, "checks": checks}
