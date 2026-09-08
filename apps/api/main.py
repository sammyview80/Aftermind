from fastapi import FastAPI

from apps.api.rest import checkpoint, health, observe, recall

app = FastAPI(title="Aftermind", description="Persistent, framework-neutral memory for AI agents.")

app.include_router(health.router)
app.include_router(observe.router)
app.include_router(recall.router)
app.include_router(checkpoint.router)
