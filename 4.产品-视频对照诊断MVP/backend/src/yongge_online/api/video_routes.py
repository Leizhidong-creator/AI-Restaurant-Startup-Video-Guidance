from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.api.dependencies import get_db_session
from yongge_online.db.models import VideoResolutionEvent
from yongge_online.videos import link_source
from yongge_online.videos.schemas import (
    DeconstructionRead,
    VideoAssetRead,
    VideoSourceStatusRead,
    VideoUrlPreviewRead,
    VideoUrlRequest,
)
from yongge_online.videos.service import VideoService

router = APIRouter(prefix="/api/v1", tags=["videos"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def build_service(request: Request, session: AsyncSession) -> VideoService:
    settings = request.app.state.settings
    return VideoService(
        session,
        request.app.state.storage,
        request.app.state.video_provider,
        max_upload_mb=settings.max_upload_mb,
        deconstructor=getattr(request.app.state, "case_deconstructor", None),
        platform_retriever=request.app.state.platform_retriever_factory(session),
        link_relevance_checker=request.app.state.video_link_relevance_checker,
    )


@router.get("/system/video-source-status", response_model=VideoSourceStatusRead)
async def get_video_source_status(session: DbSession) -> VideoSourceStatusRead:
    latest = await session.scalar(
        select(VideoResolutionEvent)
        .order_by(VideoResolutionEvent.created_at.desc())
        .limit(1)
    )
    since = datetime.now(UTC) - timedelta(hours=24)
    resolutions_24h = await session.scalar(
        select(func.count(VideoResolutionEvent.id)).where(
            VideoResolutionEvent.created_at >= since
        )
    )
    fallbacks_24h = await session.scalar(
        select(func.count(VideoResolutionEvent.id)).where(
            VideoResolutionEvent.created_at >= since,
            VideoResolutionEvent.fallback_used.is_(True),
        )
    )
    cookie_failures_24h = await session.scalar(
        select(func.count(VideoResolutionEvent.id)).where(
            VideoResolutionEvent.created_at >= since,
            VideoResolutionEvent.primary_failure_reason.in_(
                ("cookie_missing", "cookie_invalid_or_expired")
            ),
        )
    )

    if latest is None:
        current_status = "unknown"
    elif latest.selected_provider == "yt-dlp":
        current_status = "healthy"
    elif latest.primary_failure_reason in (
        "cookie_missing",
        "cookie_invalid_or_expired",
    ):
        current_status = "degraded_cookie"
    else:
        current_status = "degraded_primary"

    return VideoSourceStatusRead(
        status=current_status,
        cookie_file_configured=link_source.cookies_configured(),
        last_resolution_at=latest.created_at if latest else None,
        last_selected_provider=latest.selected_provider if latest else None,
        last_primary_failure_reason=(latest.primary_failure_reason if latest else None),
        resolutions_24h=resolutions_24h or 0,
        fallbacks_24h=fallbacks_24h or 0,
        cookie_failures_24h=cookie_failures_24h or 0,
    )


@router.post(
    "/stores/{store_id}/videos",
    response_model=VideoAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_video(
    store_id: str,
    request: Request,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> VideoAssetRead:
    asset = await build_service(request, session).upload(store_id, file)
    return VideoAssetRead.model_validate(asset)


@router.post(
    "/stores/{store_id}/videos/from-url/preview",
    response_model=VideoUrlPreviewRead,
)
async def preview_video_url(
    store_id: str,
    payload: VideoUrlRequest,
    request: Request,
    session: DbSession,
) -> VideoUrlPreviewRead:
    return await build_service(request, session).preview_url(store_id, payload.url)


@router.post(
    "/stores/{store_id}/videos/from-url",
    response_model=VideoAssetRead,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_video_url(
    store_id: str,
    payload: VideoUrlRequest,
    request: Request,
    session: DbSession,
) -> VideoAssetRead:
    asset = await build_service(request, session).ingest_url(store_id, payload.url)
    return VideoAssetRead.model_validate(asset)


@router.get("/videos/{video_id}", response_model=VideoAssetRead)
async def get_video(video_id: str, request: Request, session: DbSession) -> VideoAssetRead:
    asset = await build_service(request, session).get(video_id)
    return VideoAssetRead.model_validate(asset)


@router.post("/videos/{video_id}/analyze", response_model=VideoAssetRead)
async def analyze_video(video_id: str, request: Request, session: DbSession) -> VideoAssetRead:
    asset = await build_service(request, session).analyze(video_id)
    return VideoAssetRead.model_validate(asset)


@router.post("/videos/{video_id}/deconstruct", response_model=DeconstructionRead)
async def deconstruct_video(
    video_id: str, request: Request, session: DbSession
) -> DeconstructionRead:
    record = await build_service(request, session).deconstruct(video_id)
    return DeconstructionRead.model_validate(record)


