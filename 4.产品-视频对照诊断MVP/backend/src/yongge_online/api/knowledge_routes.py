from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.api.dependencies import get_db_session
from yongge_online.knowledge.schemas import (
    KnowledgeRead,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from yongge_online.knowledge.service import KnowledgeService

router = APIRouter(prefix="/api/v1", tags=["knowledge"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/stores/{store_id}/knowledge", response_model=list[KnowledgeRead])
async def list_knowledge(store_id: str, session: DbSession) -> list[KnowledgeRead]:
    items = await KnowledgeService(session).list_for_store(store_id)
    return [KnowledgeRead.model_validate(item) for item in items]


@router.post(
    "/stores/{store_id}/knowledge/search",
    response_model=KnowledgeSearchResponse,
)
async def search_knowledge(
    store_id: str,
    payload: KnowledgeSearchRequest,
    session: DbSession,
) -> KnowledgeSearchResponse:
    hits = await KnowledgeService(session).search(store_id, payload.query, payload.limit)
    return KnowledgeSearchResponse(hits=hits)


