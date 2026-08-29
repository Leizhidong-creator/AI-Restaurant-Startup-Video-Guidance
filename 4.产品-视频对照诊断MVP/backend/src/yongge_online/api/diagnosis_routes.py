from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.api.dependencies import get_db_session
from yongge_online.db.models import ReportRecord, SessionEvent, ToolCall
from yongge_online.diagnosis.schemas import (
    DiagnosisReport,
    DiagnosisSessionRead,
    ReportRead,
    SessionEventCreate,
    SessionEventRead,
    ToolCallRead,
    ToolExecuteRequest,
)
from yongge_online.diagnosis.service import DiagnosisService
from yongge_online.skills.ports import SkillAdvanceRequest, SkillAdvanceResult

router = APIRouter(prefix="/api/v1", tags=["diagnosis"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def build_service(request: Request, session: AsyncSession) -> DiagnosisService:
    return DiagnosisService(
        session,
        report_provider=request.app.state.report_provider,
        map_provider=request.app.state.map_provider,
        private_retriever_factory=request.app.state.private_retriever_factory,
        platform_retriever_factory=request.app.state.platform_retriever_factory,
    )


def event_read(event: SessionEvent) -> SessionEventRead:
    return SessionEventRead(
        id=event.id,
        session_id=event.session_id,
        sequence=event.sequence,
        event_type=event.event_type,
        actor=event.actor,
        payload=event.payload_json,
        created_at=event.created_at,
    )


def tool_read(tool: ToolCall) -> ToolCallRead:
    return ToolCallRead(
        id=tool.id,
        session_id=tool.session_id,
        call_id=tool.call_id,
        tool_name=tool.tool_name,
        arguments=tool.arguments_json,
        result=tool.result_json,
        status=tool.status,
        duration_ms=tool.duration_ms,
        created_at=tool.created_at,
    )


def report_read(record: ReportRecord) -> ReportRead:
    return ReportRead(
        id=record.id,
        session_id=record.session_id,
        version=record.version,
        report=DiagnosisReport.model_validate(record.report_json),
        is_fallback=record.is_fallback,
        created_at=record.created_at,
    )


@router.post(
    "/stores/{store_id}/sessions",
    response_model=DiagnosisSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    store_id: str,
    request: Request,
    session: DbSession,
) -> DiagnosisSessionRead:
    result = await build_service(request, session).create_session(store_id)
    return DiagnosisSessionRead.model_validate(result)


@router.get("/sessions", response_model=list[DiagnosisSessionRead])
async def list_sessions(
    request: Request,
    session: DbSession,
    limit: int = 20,
) -> list[DiagnosisSessionRead]:
    records = await build_service(request, session).list_sessions(limit=min(limit, 100))
    return [DiagnosisSessionRead.model_validate(item) for item in records]


@router.get("/sessions/{session_id}/events", response_model=list[SessionEventRead])
async def list_events(
    session_id: str,
    request: Request,
    session: DbSession,
) -> list[SessionEventRead]:
    events = await build_service(request, session).list_events(session_id)
    return [event_read(event) for event in events]


@router.post(
    "/sessions/{session_id}/events",
    response_model=SessionEventRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_event(
    session_id: str,
    payload: SessionEventCreate,
    request: Request,
    session: DbSession,
) -> SessionEventRead:
    event = await build_service(request, session).add_event(session_id, payload)
    return event_read(event)


@router.post("/sessions/{session_id}/tools/execute", response_model=ToolCallRead)
async def execute_tool(
    session_id: str,
    payload: ToolExecuteRequest,
    request: Request,
    session: DbSession,
) -> ToolCallRead:
    tool = await build_service(request, session).execute_tool(session_id, payload)
    return tool_read(tool)


@router.post(
    "/sessions/{session_id}/skill/advance",
    response_model=SkillAdvanceResult,
)
async def advance_skill(
    session_id: str,
    payload: SkillAdvanceRequest,
    request: Request,
    session: DbSession,
) -> SkillAdvanceResult:
    return await build_service(request, session).advance_skill(
        session_id,
        payload,
        request.app.state.skill_engine,
    )


@router.post("/sessions/{session_id}/complete", response_model=ReportRead)
async def complete_session(
    session_id: str,
    request: Request,
    session: DbSession,
) -> ReportRead:
    record = await build_service(request, session).complete(session_id)
    return report_read(record)


@router.get("/sessions/{session_id}/report", response_model=ReportRead)
async def get_report(
    session_id: str,
    request: Request,
    session: DbSession,
) -> ReportRead:
    record = await build_service(request, session).get_report(session_id)
    return report_read(record)


