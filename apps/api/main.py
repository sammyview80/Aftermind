import logging
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from apps.api.deps import get_service, get_settings, get_sync_worker
from apps.api.rest import checkpoint, consolidate, health, maintenance, observability, observe, recall

_LOG = logging.getLogger("aftermind.api")

try:
    from apps.api.mcp.server import build_asgi_app

    # build_asgi_app's underlying session manager needs its lifespan
    # (an anyio task group) started — Starlette's Mount does NOT
    # propagate ASGI lifespan events to sub-apps on its own, so it has
    # to be entered explicitly from the outer app's lifespan below.
    mcp_app = build_asgi_app(get_service())
except ImportError:
    # `mcp` package not installed — REST API still works standalone;
    # install it (pip install mcp) to expose /mcp for MCP clients.
    mcp_app = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    worker = None
    # Crash recovery runs regardless of whether a worker thread is enabled:
    # a job left "running" by a dead process must never depend on a
    # background loop that this deployment may have turned off.
    get_sync_worker().recover()
    if settings.sync_worker_enabled:
        # Crash recovery + retry loop for graph/document sync, in-process.
        # Run `aftermind worker` as a separate process and set
        # AFTERMIND_SYNC_WORKER=false here to scale them independently.
        worker = get_sync_worker()
        worker.start()
        _LOG.info("sync worker started (mode=%s, poll=%ss)", settings.sync_mode, settings.sync_poll_seconds)

    async with AsyncExitStack() as stack:
        if mcp_app is not None:
            await stack.enter_async_context(mcp_app.router.lifespan_context(mcp_app))
        try:
            yield
        finally:
            if worker is not None:
                worker.stop()


app = FastAPI(
    title="Aftermind",
    description="Persistent, framework-neutral memory for AI agents.",
    lifespan=lifespan,
)

app.include_router(health.router)
app.include_router(observe.router)
app.include_router(recall.router)
app.include_router(checkpoint.router)
app.include_router(consolidate.router)
app.include_router(maintenance.router)
app.include_router(observability.router)

if mcp_app is not None:
    app.mount("/mcp", mcp_app)
