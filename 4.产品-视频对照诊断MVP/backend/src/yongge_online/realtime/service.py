from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.core.errors import DomainError, ExternalServiceError
from yongge_online.db.models import VideoAsset, VideoDeconstruction
from yongge_online.diagnosis.service import DiagnosisService
from yongge_online.knowledge.platform import DatabasePlatformKnowledgeRetriever
from yongge_online.knowledge.ports import (
    KnowledgeRetrieverPort,
    PlatformKnowledgeRetrieverPort,
)
from yongge_online.knowledge.service import DatabaseKnowledgeRetriever
from yongge_online.realtime.schemas import RealtimeConfig
from yongge_online.skills.ports import SkillContext, SkillEnginePort
from yongge_online.tools.map_provider import MapProviderPort
from yongge_online.tools.registry import ToolRegistry
from yongge_online.tools.schemas import StoreSnapshot


class RealtimeService:
    def __init__(
        self,
        *,
        api_key: str | None,
        host: str | None,
        model: str,
        timeout_seconds: float,
        voice: str | None = None,
        fallback_voice: str = "Ethan",
        map_provider: MapProviderPort,
        skill_engine: SkillEnginePort,
        private_retriever_factory: Callable[
            [AsyncSession], KnowledgeRetrieverPort
        ] = DatabaseKnowledgeRetriever,
        platform_retriever_factory: Callable[
            [AsyncSession], PlatformKnowledgeRetrieverPort
        ] = DatabasePlatformKnowledgeRetriever,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key
        self.host = host
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.voice = voice or fallback_voice
        self.map_provider = map_provider
        self.skill_engine = skill_engine
        self.private_retriever_factory = private_retriever_factory
        self.platform_retriever_factory = platform_retriever_factory
        self.transport = transport

    async def session_config(
        self,
        *,
        session_id: str,
        db_session: AsyncSession,
    ) -> RealtimeConfig:
        diagnosis = await DiagnosisService(
            db_session,
            report_provider=_UnusedReportProvider(),
            map_provider=self.map_provider,
        ).get_session(session_id)
        store = StoreSnapshot.model_validate(diagnosis.store_snapshot_json)
        case_context = await self._load_case_context(
            db_session, store_id=diagnosis.store_id
        )
        instructions = await self.skill_engine.build_session_instructions(
            SkillContext(
                session_id=session_id, store=store, case_context=case_context
            )
        )
        registry = ToolRegistry(
            store=store,
            retriever=self.private_retriever_factory(db_session),
            platform_retriever=self.platform_retriever_factory(db_session),
            map_provider=self.map_provider,
        )
        realtime_tools = [self._to_realtime_tool(tool) for tool in registry.definitions]
        return RealtimeConfig(
            model=self.model,
            sdp_endpoint=f"/api/v1/realtime/sdp?session_id={session_id}",
            session_update={
                "type": "session.update",
                "session": {
                    "voice": self.voice,
                    "instructions": instructions,
                    "modalities": ["text", "audio"],
                    "input_audio_format": "pcm",
                    "output_audio_format": "pcm",
                    "input_audio_transcription": {
                        "model": "qwen3-asr-flash-realtime"
                    },
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 500,
                        "silence_duration_ms": 800,
                    },
                    "tools": realtime_tools,
                },
            },
        )

    @staticmethod
    async def _load_case_context(
        db_session: AsyncSession, *, store_id: str
    ) -> dict[str, Any] | None:
        """取该门店最近一次解析完成的案例(摘要+四维初判),注入连麦专家指令。"""
        asset = await db_session.scalar(
            select(VideoAsset)
            .where(VideoAsset.store_id == store_id, VideoAsset.status == "completed")
            .order_by(VideoAsset.created_at.desc())
            .limit(1)
        )
        if asset is None or not asset.analysis_json:
            return None
        context: dict[str, Any] = {
            "summary": asset.analysis_json.get("summary", ""),
        }
        deconstruction = await db_session.scalar(
            select(VideoDeconstruction).where(VideoDeconstruction.video_id == asset.id)
        )
        if deconstruction is not None and not deconstruction.is_fallback:
            context["deconstruction"] = deconstruction.result_json
        return context

    async def exchange_sdp(
        self,
        *,
        session_id: str,
        offer_sdp: str,
        db_session: AsyncSession,
    ) -> str:
        await DiagnosisService(
            db_session,
            report_provider=_UnusedReportProvider(),
            map_provider=self.map_provider,
        ).get_session(session_id)
        if not offer_sdp.strip():
            raise DomainError("Offer SDP 不能为空", code="invalid_sdp", status_code=422)
        if not self.api_key or not self.host:
            raise ExternalServiceError("Qwen Realtime", "未配置百炼 API Key 或 API Host")

        url = f"https://{self.host}/api/v1/webrtc/realtime"
        try:
            async with httpx.AsyncClient(
                transport=self.transport,
                timeout=self.timeout_seconds,
            ) as client:
                response = await client.post(
                    url,
                    params={"model": self.model},
                    content=offer_sdp.encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/sdp",
                    },
                )
            if not response.is_success:
                raise ExternalServiceError(
                    "Qwen Realtime",
                    f"SDP 交换返回 HTTP {response.status_code}",
                    retryable=response.status_code >= 500,
                )
            return response.text
        except ExternalServiceError:
            raise
        except httpx.HTTPError as exc:
            raise ExternalServiceError("Qwen Realtime", str(exc)) from exc

    @staticmethod
    def _to_realtime_tool(tool: dict[str, Any]) -> dict[str, Any]:
        function = tool["function"]
        return {
            "type": "function",
            "function": {
                "name": function["name"],
                "description": function["description"],
                "parameters": function["parameters"],
            },
        }


class _UnusedReportProvider:
    async def generate_report(self, *, context: dict):
        del context
        raise RuntimeError("report generation is not used by realtime configuration")


