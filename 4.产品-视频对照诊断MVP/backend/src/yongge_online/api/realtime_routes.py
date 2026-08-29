from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.api.dependencies import get_db_session
from yongge_online.realtime.schemas import RealtimeConfig

router = APIRouter(prefix="/api/v1/realtime", tags=["realtime"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


@router.get("/config/{session_id}", response_model=RealtimeConfig)
async def realtime_config(
    session_id: str,
    request: Request,
    session: DbSession,
) -> RealtimeConfig:
    return await request.app.state.realtime_service.session_config(
        session_id=session_id,
        db_session=session,
    )


@router.post("/sdp")
async def exchange_sdp(
    session_id: str,
    request: Request,
    session: DbSession,
) -> Response:
    offer_sdp = (await request.body()).decode("utf-8")
    answer_sdp = await request.app.state.realtime_service.exchange_sdp(
        session_id=session_id,
        offer_sdp=offer_sdp,
        db_session=session,
    )
    return Response(content=answer_sdp, media_type="application/sdp")


