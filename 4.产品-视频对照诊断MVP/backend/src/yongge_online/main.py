from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.ai.ports import (
    CaseDeconstructorPort,
    ReportGeneratorPort,
    VideoLinkRelevancePort,
    VideoUnderstandingPort,
)
from yongge_online.ai.qwen import (
    QwenCaseDeconstructor,
    QwenReportGenerator,
    QwenVideoLinkRelevanceChecker,
    QwenVideoUnderstanding,
    UnavailableCaseDeconstructor,
    UnavailableReportGenerator,
    UnavailableVideoLinkRelevanceChecker,
    UnavailableVideoUnderstanding,
)
from yongge_online.api.asr_routes import router as asr_router
from yongge_online.api.diagnosis_routes import router as diagnosis_router
from yongge_online.api.knowledge_routes import router as knowledge_router
from yongge_online.api.profile_routes import router as profile_router
from yongge_online.api.realtime_routes import router as realtime_router
from yongge_online.api.video_routes import router as video_router
from yongge_online.asr.service import AsrProxyService
from yongge_online.core.config import Settings, get_settings
from yongge_online.core.errors import DomainError
from yongge_online.db.session import Database
from yongge_online.knowledge.platform import DatabasePlatformKnowledgeRetriever
from yongge_online.knowledge.ports import (
    KnowledgeRetrieverPort,
    PlatformKnowledgeRetrieverPort,
)
from yongge_online.knowledge.service import DatabaseKnowledgeRetriever
from yongge_online.realtime.service import RealtimeService
from yongge_online.skills.default import DefaultRestaurantSkill
from yongge_online.skills.ports import SkillEnginePort
from yongge_online.storage.local import LocalObjectStorage
from yongge_online.tools.map_provider import (
    AmapWebServiceProvider,
    MapProviderPort,
    UnavailableMapProvider,
)


def create_app(
    settings: Settings | None = None,
    *,
    video_provider: VideoUnderstandingPort | None = None,
    video_link_relevance_checker: VideoLinkRelevancePort | None = None,
    report_provider: ReportGeneratorPort | None = None,
    case_deconstructor: CaseDeconstructorPort | None = None,
    map_provider: MapProviderPort | None = None,
    skill_engine: SkillEnginePort | None = None,
    private_retriever_factory: Callable[
        [AsyncSession], KnowledgeRetrieverPort
    ] | None = None,
    platform_retriever_factory: Callable[
        [AsyncSession], PlatformKnowledgeRetrieverPort
    ] | None = None,
    realtime_http_transport: httpx.AsyncBaseTransport | None = None,
    asr_connector: Callable[..., object] | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    if resolved_settings.database_url.startswith("sqlite"):
        Path("data").mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        database = Database(resolved_settings.database_url)
        await database.create_schema()
        app.state.db = database
        app.state.storage = LocalObjectStorage(resolved_settings.upload_dir)
        if video_provider is not None:
            app.state.video_provider = video_provider
        elif (
            resolved_settings.dashscope_api_key
            and resolved_settings.dashscope_openai_base_url
        ):
            app.state.video_provider = QwenVideoUnderstanding(
                api_key=resolved_settings.dashscope_api_key.get_secret_value(),
                base_url=resolved_settings.dashscope_openai_base_url,
                model=resolved_settings.qwen_video_model,
                timeout_seconds=resolved_settings.external_timeout_seconds,
            )
        else:
            app.state.video_provider = UnavailableVideoUnderstanding()
        if video_link_relevance_checker is not None:
            app.state.video_link_relevance_checker = video_link_relevance_checker
        elif (
            resolved_settings.dashscope_api_key
            and resolved_settings.dashscope_openai_base_url
        ):
            app.state.video_link_relevance_checker = QwenVideoLinkRelevanceChecker(
                api_key=resolved_settings.dashscope_api_key.get_secret_value(),
                base_url=resolved_settings.dashscope_openai_base_url,
                model=resolved_settings.qwen_agent_model,
                timeout_seconds=resolved_settings.external_timeout_seconds,
            )
        else:
            app.state.video_link_relevance_checker = (
                UnavailableVideoLinkRelevanceChecker()
            )
        if report_provider is not None:
            app.state.report_provider = report_provider
        elif (
            resolved_settings.dashscope_api_key
            and resolved_settings.dashscope_openai_base_url
        ):
            app.state.report_provider = QwenReportGenerator(
                api_key=resolved_settings.dashscope_api_key.get_secret_value(),
                base_url=resolved_settings.dashscope_openai_base_url,
                model=resolved_settings.qwen_agent_model,
                timeout_seconds=resolved_settings.external_timeout_seconds,
            )
        else:
            app.state.report_provider = UnavailableReportGenerator()
        if case_deconstructor is not None:
            app.state.case_deconstructor = case_deconstructor
        elif (
            resolved_settings.dashscope_api_key
            and resolved_settings.dashscope_openai_base_url
        ):
            app.state.case_deconstructor = QwenCaseDeconstructor(
                api_key=resolved_settings.dashscope_api_key.get_secret_value(),
                base_url=resolved_settings.dashscope_openai_base_url,
                model=resolved_settings.qwen_agent_model,
                timeout_seconds=resolved_settings.external_timeout_seconds,
            )
        else:
            app.state.case_deconstructor = UnavailableCaseDeconstructor()
        if map_provider is not None:
            app.state.map_provider = map_provider
        elif resolved_settings.amap_web_service_key:
            app.state.map_provider = AmapWebServiceProvider(
                api_key=resolved_settings.amap_web_service_key.get_secret_value(),
                timeout_seconds=resolved_settings.external_timeout_seconds,
            )
        else:
            app.state.map_provider = UnavailableMapProvider("未配置高德 Web 服务 Key")
        app.state.skill_engine = skill_engine or DefaultRestaurantSkill()
        app.state.private_retriever_factory = (
            private_retriever_factory or DatabaseKnowledgeRetriever
        )
        app.state.platform_retriever_factory = (
            platform_retriever_factory or DatabasePlatformKnowledgeRetriever
        )
        app.state.realtime_service = RealtimeService(
            api_key=(
                resolved_settings.dashscope_api_key.get_secret_value()
                if resolved_settings.dashscope_api_key
                else None
            ),
            host=resolved_settings.dashscope_host,
            model=resolved_settings.qwen_realtime_model,
            voice=resolved_settings.qwen_realtime_voice,
            fallback_voice=resolved_settings.qwen_realtime_fallback_voice,
            timeout_seconds=resolved_settings.external_timeout_seconds,
            map_provider=app.state.map_provider,
            skill_engine=app.state.skill_engine,
            private_retriever_factory=app.state.private_retriever_factory,
            platform_retriever_factory=app.state.platform_retriever_factory,
            transport=realtime_http_transport,
        )
        allowed_asr_origins = set(resolved_settings.cors_origins)
        if resolved_settings.public_base_url:
            allowed_asr_origins.add(resolved_settings.public_base_url)
        app.state.asr_service = AsrProxyService(
            api_key=(
                resolved_settings.dashscope_api_key.get_secret_value()
                if resolved_settings.dashscope_api_key
                else None
            ),
            websocket_url=resolved_settings.dashscope_asr_ws_url,
            allowed_origins=allowed_asr_origins,
            max_seconds=resolved_settings.asr_max_seconds,
            timeout_seconds=resolved_settings.external_timeout_seconds,
            connector=asr_connector,
        )
        try:
            yield
        finally:
            await database.dispose()

    app = FastAPI(
        title="餐饮专家在线 API",
        version="0.1.0",
        description="任务 3：后端与完整业务链路",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def handle_domain_error(_request: Request, exc: DomainError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": resolved_settings.app_name}

    app.include_router(profile_router)
    app.include_router(video_router)
    app.include_router(knowledge_router)
    app.include_router(diagnosis_router)
    app.include_router(realtime_router)
    app.include_router(asr_router)
    return app


app = create_app()


