from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from apps.api.deps import get_service
from apps.api.rest.schemas import MemorySummary, ScopeRequest
from core.facade import AftermindService
from domain.models.recall_query import RecallQuery

router = APIRouter()


class RecallRequest(BaseModel):
    scope: ScopeRequest = ScopeRequest()
    text: str = ""
    limit: int = 10


class RecallResponse(BaseModel):
    context: str
    memories: list[MemorySummary]
    related_entities: list[str]
    trace_id: str
    recall_sources: list[str] = []
    recall_latency_ms: float | None = None


class SearchRequest(BaseModel):
    scope: ScopeRequest = ScopeRequest()
    query: str
    limit: int = 5


class SearchResponse(BaseModel):
    memories: list[MemorySummary]


def _summarize(memories) -> list[MemorySummary]:
    return [
        MemorySummary(
            memory_id=m.memory_id, content=m.content, memory_type=m.memory_type.value, confidence=m.confidence
        )
        for m in memories
    ]


@router.post("/recall", response_model=RecallResponse)
def recall(
    request: RecallRequest, response: Response, service: AftermindService = Depends(get_service)
) -> RecallResponse:
    scope = request.scope.to_domain()
    with service.tracer.begin("recall", scope=scope.key() if scope else None) as t:
        result = service.recall(RecallQuery(scope=scope, text=request.text, limit=request.limit))
    response.headers["X-Aftermind-Trace-Id"] = t.trace_id
    return RecallResponse(
        context=result.context,
        memories=_summarize(result.memories),
        related_entities=list(result.related_entities),
        trace_id=t.trace_id,
        recall_sources=list(t.fields.get("recall_sources", [])),
        recall_latency_ms=t.latency_ms,
    )


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest, service: AftermindService = Depends(get_service)) -> SearchResponse:
    memories = service.search(request.query, scope=request.scope.to_domain(), limit=request.limit)
    return SearchResponse(memories=_summarize(memories))
