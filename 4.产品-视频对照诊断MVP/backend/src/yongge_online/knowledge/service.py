import re
from collections.abc import Iterable
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.ai.ports import ExtractedKnowledge, TranscriptSegment, VideoAnalysis
from yongge_online.core.errors import NotFoundError
from yongge_online.db.models import KnowledgeItem, Store
from yongge_online.knowledge.schemas import KnowledgeHit


class KnowledgeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def replace_video_knowledge(
        self,
        *,
        user_id: str,
        store_id: str,
        video_id: str,
        analysis: VideoAnalysis,
    ) -> None:
        await self.session.execute(
            delete(KnowledgeItem).where(
                KnowledgeItem.source_type == "video",
                KnowledgeItem.source_id == video_id,
            )
        )
        self.session.add(
            self._item(
                user_id=user_id,
                store_id=store_id,
                video_id=video_id,
                kind="summary",
                content=analysis.summary,
            )
        )
        for segment in analysis.transcript:
            self.session.add(
                self._transcript_item(user_id, store_id, video_id, segment)
            )
        for kind, items in (
            ("claim", analysis.claims),
            ("risk", analysis.risks),
            ("case", analysis.cases),
            ("action", analysis.actions),
        ):
            for extracted in items:
                self.session.add(
                    self._extracted_item(
                        user_id,
                        store_id,
                        video_id,
                        kind,
                        extracted,
                    )
                )

    def _item(
        self,
        *,
        user_id: str,
        store_id: str,
        video_id: str,
        kind: str,
        content: str,
        tags: list[str] | None = None,
        start_ms: int | None = None,
        end_ms: int | None = None,
        confidence: float | None = None,
    ) -> KnowledgeItem:
        return KnowledgeItem(
            id=str(uuid4()),
            user_id=user_id,
            store_id=store_id,
            source_type="video",
            source_id=video_id,
            kind=kind,
            content=content,
            tags_json=tags or [],
            start_ms=start_ms,
            end_ms=end_ms,
            confidence=confidence,
        )

    def _transcript_item(
        self,
        user_id: str,
        store_id: str,
        video_id: str,
        segment: TranscriptSegment,
    ) -> KnowledgeItem:
        prefix = f"{segment.speaker}：" if segment.speaker else ""
        return self._item(
            user_id=user_id,
            store_id=store_id,
            video_id=video_id,
            kind="transcript",
            content=f"{prefix}{segment.text}",
            tags=["转写"],
            start_ms=segment.start_ms,
            end_ms=segment.end_ms,
        )

    def _extracted_item(
        self,
        user_id: str,
        store_id: str,
        video_id: str,
        kind: str,
        item: ExtractedKnowledge,
    ) -> KnowledgeItem:
        return self._item(
            user_id=user_id,
            store_id=store_id,
            video_id=video_id,
            kind=kind,
            content=item.content,
            tags=item.tags,
            start_ms=item.start_ms,
            end_ms=item.end_ms,
            confidence=item.confidence,
        )

    async def list_for_store(self, store_id: str) -> list[KnowledgeItem]:
        if await self.session.get(Store, store_id) is None:
            raise NotFoundError("门店")
        result = await self.session.scalars(
            select(KnowledgeItem)
            .where(KnowledgeItem.store_id == store_id)
            .order_by(KnowledgeItem.created_at, KnowledgeItem.id)
        )
        return list(result)

    async def search(self, store_id: str, query: str, limit: int) -> list[KnowledgeHit]:
        items = await self.list_for_store(store_id)
        scored = [
            (
                self._score(query, item.content, item.tags_json)
                + self._kind_priority(item.kind),
                item,
            )
            for item in items
        ]
        scored.sort(key=lambda pair: (-pair[0], pair[1].created_at, pair[1].id))
        return [
            KnowledgeHit(
                id=item.id,
                kind=item.kind,
                content=item.content,
                tags=item.tags_json,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                score=score,
            )
            for score, item in scored[:limit]
            if score > 0
        ]

    @staticmethod
    def _score(query: str, content: str, tags: Iterable[str]) -> float:
        normalized_query = query.casefold().strip()
        searchable = f"{content} {' '.join(tags)}".casefold()
        score = 10.0 if normalized_query in searchable else 0.0
        tokens = [token for token in re.split(r"[\s,，。！？;；]+", normalized_query) if token]
        score += sum(2.0 for token in tokens if token in searchable)
        return score

    @staticmethod
    def _kind_priority(kind: str) -> float:
        return {
            "claim": 1.0,
            "risk": 0.9,
            "action": 0.8,
            "case": 0.7,
            "summary": 0.5,
            "transcript": 0.0,
        }.get(kind, 0.0)


class DatabaseKnowledgeRetriever:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(
        self,
        *,
        user_id: str,
        store_id: str,
        query: str,
        limit: int,
    ) -> list[KnowledgeHit]:
        store = await self.session.get(Store, store_id)
        if store is None or store.user_id != user_id:
            raise NotFoundError("门店")
        return await KnowledgeService(self.session).search(store_id, query, limit)


