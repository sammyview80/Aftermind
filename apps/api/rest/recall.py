from fastapi import APIRouter, Depends
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
def recall(request: RecallRequest, service: AftermindService = Depends(get_service)) -> RecallResponse:
    result = service.recall(RecallQuery(scope=request.scope.to_domain(), text=request.text, limit=request.limit))
    return RecallResponse(
        context=result.context,
        memories=_summarize(result.memories),
        related_entities=list(result.related_entities),
    )


@router.post("/search", response_model=SearchResponse)
def search(request: SearchRequest, service: AftermindService = Depends(get_service)) -> SearchResponse:
    memories = service.search(request.query, scope=request.scope.to_domain(), limit=request.limit)
    return SearchResponse(memories=_summarize(memories))
