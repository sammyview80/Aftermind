from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from apps.api.deps import get_service
from apps.api.rest import checkpoint, consolidate, health, observe, recall

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
    async with AsyncExitStack() as stack:
        if mcp_app is not None:
            await stack.enter_async_context(mcp_app.router.lifespan_context(mcp_app))
        yield


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

if mcp_app is not None:
    app.mount("/mcp", mcp_app)
