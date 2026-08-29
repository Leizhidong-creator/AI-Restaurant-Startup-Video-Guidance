import asyncio
import hashlib
import logging
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.ai.ports import (
    CaseDeconstructorPort,
    VideoAnalysis,
    VideoLinkRelevancePort,
    VideoUnderstandingPort,
)
from yongge_online.core.errors import DomainError, NotFoundError
from yongge_online.db.models import (
    Store,
    VideoAsset,
    VideoDeconstruction,
    VideoResolutionEvent,
)
from yongge_online.knowledge.ports import PlatformKnowledgeRetrieverPort
from yongge_online.knowledge.service import KnowledgeService
from yongge_online.storage.ports import ObjectStoragePort
from yongge_online.videos import link_source
from yongge_online.videos.schemas import (
    CaseDeconstruction,
    DimensionInsight,
    TransferVerdict,
    VideoLinkRelevance,
    VideoUrlPreviewRead,
)

ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".flv", ".wmv"}
ALLOWED_VIDEO_CONTENT_TYPES = {
    "video/mp4",
    "video/quicktime",
    "video/x-msvideo",
    "video/x-matroska",
    "video/x-flv",
    "video/x-ms-wmv",
}
logger = logging.getLogger(__name__)


class VideoService:
    def __init__(
        self,
        session: AsyncSession,
        storage: ObjectStoragePort,
        provider: VideoUnderstandingPort,
        *,
        max_upload_mb: int,
        deconstructor: CaseDeconstructorPort | None = None,
        platform_retriever: PlatformKnowledgeRetrieverPort | None = None,
        link_relevance_checker: VideoLinkRelevancePort | None = None,
    ):
        self.session = session
        self.storage = storage
        self.provider = provider
        self.max_upload_bytes = max_upload_mb * 1024 * 1024
        self.deconstructor = deconstructor
        self.platform_retriever = platform_retriever
        self.link_relevance_checker = link_relevance_checker

    async def preview_url(self, store_id: str, url: str) -> VideoUrlPreviewRead:
        if await self.session.get(Store, store_id) is None:
            raise NotFoundError("门店")
        metadata = await asyncio.to_thread(link_source.preview_video_url, url)
        if self.link_relevance_checker is None:
            relevance = VideoLinkRelevance.UNCERTAIN
            reason = "暂时无法判断，继续由用户决定"
        else:
            try:
                result = await self.link_relevance_checker.check_link_metadata(
                    title=metadata.title,
                    description=metadata.description,
                )
                relevance = result.relevance
                reason = result.reason
            except Exception:
                logger.exception("video_link_relevance_check_failed")
                relevance = VideoLinkRelevance.UNCERTAIN
                reason = "暂时无法判断，继续由用户决定"
        return VideoUrlPreviewRead(
            title=metadata.title,
            description=metadata.description,
            relevance=relevance,
            reason=reason,
        )

    async def upload(self, store_id: str, file: UploadFile) -> VideoAsset:
        store = await self.session.get(Store, store_id)
        if store is None:
            raise NotFoundError("门店")

        filename = file.filename or "video"
        suffix = Path(filename).suffix.lower()
        content_type = (file.content_type or "").lower()
        if suffix not in ALLOWED_VIDEO_SUFFIXES or content_type not in ALLOWED_VIDEO_CONTENT_TYPES:
            raise DomainError(
                "仅支持 MP4、MOV、AVI、MKV、FLV、WMV 视频",
                code="invalid_video",
                status_code=422,
            )

        content = await file.read(self.max_upload_bytes + 1)
        if len(content) > self.max_upload_bytes:
            raise DomainError(
                f"视频超过 {self.max_upload_bytes // 1024 // 1024} MB 限制",
                code="video_too_large",
                status_code=413,
            )
        if not content:
            raise DomainError("视频内容为空", code="invalid_video", status_code=422)

        return await self._store_content(
            store, filename=filename, content_type=content_type, content=content
        )

    async def ingest_url(self, store_id: str, url: str) -> VideoAsset:
        """粘贴链接 → yt-dlp 取视频 → 走与上传完全相同的落库/解析流水。"""
        store = await self.session.get(Store, store_id)
        if store is None:
            raise NotFoundError("门店")
        fetched = await asyncio.to_thread(
            link_source.fetch_video_from_url, url, max_bytes=self.max_upload_bytes
        )
        asset = await self._store_content(
            store,
            filename=fetched.filename,
            content_type=fetched.content_type,
            content=fetched.content,
        )
        await self._record_resolution_event(
            store_id=store.id,
            video_id=asset.id,
            selected_provider=fetched.source_provider,
            primary_failure_reason=fetched.primary_failure_reason,
        )
        return asset

    async def _record_resolution_event(
        self,
        *,
        store_id: str,
        video_id: str,
        selected_provider: str,
        primary_failure_reason: str | None,
    ) -> None:
        fallback_used = selected_provider != "yt-dlp"
        try:
            self.session.add(
                VideoResolutionEvent(
                    id=str(uuid4()),
                    store_id=store_id,
                    video_id=video_id,
                    selected_provider=selected_provider,
                    primary_failure_reason=primary_failure_reason,
                    fallback_used=fallback_used,
                )
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            logger.exception("video_resolution_event_write_failed")
            return

        if fallback_used:
            logger.warning(
                "video_resolver_fallback provider=%s reason=%s cookie_configured=%s",
                selected_provider,
                primary_failure_reason,
                link_source.cookies_configured(),
            )

    async def _store_content(
        self, store: Store, *, filename: str, content_type: str, content: bytes
    ) -> VideoAsset:
        suffix = Path(filename).suffix.lower()
        asset_id = str(uuid4())
        key = f"{store.user_id}/{store.id}/{asset_id}{suffix}"
        stored = await self.storage.save(key=key, content=content, content_type=content_type)
        asset = VideoAsset(
            id=asset_id,
            user_id=store.user_id,
            store_id=store.id,
            filename=filename,
            content_type=content_type,
            size_bytes=stored.size_bytes,
            storage_uri=stored.uri,
            sha256=hashlib.sha256(content).hexdigest(),
            status="uploaded",
        )
        self.session.add(asset)
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def get(self, video_id: str) -> VideoAsset:
        asset = await self.session.get(VideoAsset, video_id)
        if asset is None:
            raise NotFoundError("视频")
        return asset

    async def analyze(self, video_id: str) -> VideoAsset:
        asset = await self.get(video_id)
        if asset.status == "completed" and asset.analysis_json:
            return asset

        asset.status = "processing"
        asset.error_code = None
        asset.error_message = None
        await self.session.commit()

        try:
            analysis = await self._find_cached_analysis(asset)
            if analysis is None:
                content = await self.storage.read(asset.storage_uri)
                model_url = await self.storage.model_url(asset.storage_uri)
                analysis = await self.provider.analyze_video(
                    filename=asset.filename,
                    content_type=asset.content_type,
                    content=content,
                    model_url=model_url,
                )
            await KnowledgeService(self.session).replace_video_knowledge(
                user_id=asset.user_id,
                store_id=asset.store_id,
                video_id=asset.id,
                analysis=analysis,
            )
            asset.analysis_json = analysis.model_dump(mode="json")
            asset.status = "completed"
            await self.session.commit()
            await self.session.refresh(asset)
            return asset
        except Exception as exc:
            asset.status = "failed"
            asset.error_code = "video_analysis_failed"
            asset.error_message = str(exc)
            await self.session.commit()
            if isinstance(exc, DomainError):
                raise
            raise DomainError(
                f"视频解析失败：{exc}",
                code="video_analysis_failed",
                status_code=502,
            ) from exc

    async def deconstruct(self, video_id: str) -> VideoDeconstruction:
        asset = await self.get(video_id)
        if asset.status != "completed" or not asset.analysis_json:
            raise DomainError(
                "视频尚未完成解析，无法解构",
                code="video_not_analyzed",
                status_code=409,
            )
        existing = await self.session.scalar(
            select(VideoDeconstruction).where(VideoDeconstruction.video_id == video_id)
        )
        if existing is not None:
            return existing
        if self.deconstructor is None:
            raise DomainError(
                "解构服务未配置",
                code="deconstruction_unavailable",
                status_code=503,
            )

        # 同内容+同品类的解构结果直接复用(演示案例重跑秒出;迁移判断依赖品类,跨品类不复用)
        cached = await self._find_cached_deconstruction(asset)
        if cached is not None:
            record = VideoDeconstruction(
                id=str(uuid4()),
                video_id=video_id,
                result_json=cached.result_json,
                is_fallback=False,
            )
            self.session.add(record)
            await self.session.commit()
            await self.session.refresh(record)
            return record

        context = await self._build_deconstruction_context(asset)
        is_fallback = False
        try:
            result = await self.deconstructor.deconstruct_case(context=context)
            result = self._strip_fabricated_dimension_evidence(result, asset.analysis_json)
        except Exception as exc:
            is_fallback = True
            result = self._fallback_deconstruction(exc)

        record = VideoDeconstruction(
            id=str(uuid4()),
            video_id=video_id,
            result_json=result.model_dump(mode="json"),
            is_fallback=is_fallback,
        )
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def _find_cached_deconstruction(
        self, asset: VideoAsset
    ) -> VideoDeconstruction | None:
        store = await self.session.get(Store, asset.store_id)
        if store is None:
            return None
        result = await self.session.execute(
            select(VideoDeconstruction)
            .join(VideoAsset, VideoDeconstruction.video_id == VideoAsset.id)
            .join(Store, VideoAsset.store_id == Store.id)
            .where(
                VideoAsset.sha256 == asset.sha256,
                VideoAsset.id != asset.id,
                Store.category == store.category,
                VideoDeconstruction.is_fallback.is_(False),
            )
            .order_by(VideoDeconstruction.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _build_deconstruction_context(self, asset: VideoAsset) -> dict:
        store = await self.session.get(Store, asset.store_id)
        store_profile = {
            "name": store.name,
            "category": store.category,
            "stage": store.stage,
            "address": store.address,
            "initial_investment": (
                str(store.initial_investment) if store.initial_investment is not None else None
            ),
        }
        analysis = asset.analysis_json or {}
        platform_hits: list[dict] = []
        if self.platform_retriever is not None:
            try:
                hits = await self.platform_retriever.search(
                    query=str(analysis.get("summary", "")),
                    limit=6,
                    category=store.category,
                    stage=store.stage,
                )
                platform_hits = [
                    {"id": h.id, "content": h.content} for h in hits
                ]
            except Exception:  # KB 检索失败不阻塞解构,少一路证据而已
                platform_hits = []
        return {
            "用户建档": store_profile,
            "视频摘要": analysis.get("summary", ""),
            "视频证据": [
                {"content": c.get("content"), "start_ms": c.get("start_ms")}
                for c in analysis.get("claims", [])
            ],
            "视频风险提示": [r.get("content") for r in analysis.get("risks", [])],
            "平台经验": platform_hits,
        }

    @staticmethod
    def _strip_fabricated_dimension_evidence(
        result: CaseDeconstruction, analysis: dict
    ) -> CaseDeconstruction:
        """剥掉非逐字引用的证据,保留判断本身(校准式护栏,同 §23 2026-07-22 决策)。"""
        allowed = {
            (c.get("content") or "").strip()
            for c in analysis.get("claims", [])
        }
        for insight in (result.location, result.product, result.audience, result.operation):
            insight.evidence = [
                e for e in insight.evidence if e.content.strip() in allowed
            ]
        return result

    @staticmethod
    def _fallback_deconstruction(exc: Exception) -> CaseDeconstruction:
        def dim() -> DimensionInsight:
            return DimensionInsight(
                why_it_works="本维度解构暂时生成失败，未能给出判断。",
                evidence=[],
                transfer=TransferVerdict.TO_VERIFY,
                transfer_reason="生成服务异常，证据不足，待连麦现场确认。",
            )

        return CaseDeconstruction(
            location=dim(),
            product=dim(),
            audience=dim(),
            operation=dim(),
            overall_note=f"解构服务异常（{exc}），本结果为降级版本。",
        )

    async def _find_cached_analysis(self, asset: VideoAsset) -> VideoAnalysis | None:
        result = await self.session.execute(
            select(VideoAsset.analysis_json)
            .where(
                VideoAsset.sha256 == asset.sha256,
                VideoAsset.status == "completed",
                VideoAsset.analysis_json.is_not(None),
                VideoAsset.id != asset.id,
            )
            .limit(1)
        )
        cached = result.scalar_one_or_none()
        if cached is None:
            return None
        return VideoAnalysis.model_validate(cached)


