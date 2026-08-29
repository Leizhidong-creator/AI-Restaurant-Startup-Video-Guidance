from fastapi import APIRouter, WebSocket

router = APIRouter(tags=["asr"])


@router.websocket("/api/v1/asr/stream")
async def stream_asr(websocket: WebSocket) -> None:
    await websocket.app.state.asr_service.handle(websocket)


