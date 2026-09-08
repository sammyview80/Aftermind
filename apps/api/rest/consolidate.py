from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.deps import get_service
from apps.api.rest.schemas import ScopeRequest
from core.facade import AftermindService

router = APIRouter()


class ConsolidateRequest(BaseModel):
    scope: ScopeRequest = ScopeRequest()
    slug: str = "consolidated-knowledge"
    title: str = "Consolidated Knowledge"
    min_group_size: int = 3


class ConsolidationResultResponse(BaseModel):
    accepted: bool
    document_id: Optional[str] = None
    document_slug: Optional[str] = None
    source_memory_ids: list[str] = []
    reasoning: str = ""


class ConsolidateResponse(BaseModel):
    consolidated: list[ConsolidationResultResponse]


@router.post("/consolidate", response_model=ConsolidateResponse)
def consolidate(
    request: ConsolidateRequest, service: AftermindService = Depends(get_service)
) -> ConsolidateResponse:
    results = service.consolidate(
        scope=request.scope.to_domain(),
        slug=request.slug,
        title=request.title,
        min_group_size=request.min_group_size,
    )
    return ConsolidateResponse(
        consolidated=[
            ConsolidationResultResponse(
                accepted=r.accepted,
                document_id=r.document_id,
                document_slug=r.document_slug,
                source_memory_ids=list(r.source_memory_ids),
                reasoning=r.reasoning,
            )
            for r in results
        ]
    )
