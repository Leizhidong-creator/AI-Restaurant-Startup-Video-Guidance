from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.db.models import PlatformKnowledgeItem
from yongge_online.knowledge.schemas import KnowledgeHit, PlatformKnowledgeUpsert
from yongge_online.knowledge.service import KnowledgeService

DECISIVE_REVIEW_STATUSES = frozenset({"reviewed", "golden"})


class PlatformKnowledgeService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_many(self, entries: Iterable[PlatformKnowledgeUpsert]) -> None:
        now = datetime.now(UTC)
        for entry in entries:
            existing = await self.session.get(PlatformKnowledgeItem, entry.id)
            values = entry.model_dump()
            values["knowledge_id"] = values["knowledge_id"] or entry.id
            values["evidence_grade"] = values["evidence_grade"] or (
                entry.review_status
                if entry.review_status in DECISIVE_REVIEW_STATUSES
                else "draft"
            )
            values["tags_json"] = values.pop("tags")
            values["applicable_categories_json"] = values.pop("applicable_categories")
            values["business_stages_json"] = values.pop("business_stages")
            values["regions_json"] = values.pop("regions")
            values["applicability_json"] = values.pop("applicability")
            values["limitations_json"] = values.pop("limitations")
            if existing is None:
                self.session.add(PlatformKnowledgeItem(**values))
                continue
            for key, value in values.items():
                if key != "id":
                    setattr(existing, key, value)
            existing.updated_at = now

    async def list_all(self) -> list[PlatformKnowledgeItem]:
        result = await self.session.scalars(
            select(PlatformKnowledgeItem).order_by(
                PlatformKnowledgeItem.created_at,
                PlatformKnowledgeItem.id,
            )
        )
        return list(result)

    async def get_many(self, ids: Iterable[str]) -> list[PlatformKnowledgeItem]:
        stable_ids = tuple(dict.fromkeys(item for item in ids if item))
        if not stable_ids:
            return []
        result = await self.session.scalars(
            select(PlatformKnowledgeItem).where(PlatformKnowledgeItem.id.in_(stable_ids))
        )
        by_id = {item.id: item for item in result}
        return [by_id[item_id] for item_id in stable_ids if item_id in by_id]


class DatabasePlatformKnowledgeRetriever:
    """Safe lexical fallback; production vector RAG is injected through the same Port."""

    source = "platform_knowledge"

    def __init__(self, session: AsyncSession):
        self.session = session

    async def search(
        self,
        *,
        query: str,
        limit: int,
        category: str | None = None,
        stage: str | None = None,
        region: str | None = None,
    ) -> list[KnowledgeHit]:
        items = list(
            await self.session.scalars(
                select(PlatformKnowledgeItem).where(
                    PlatformKnowledgeItem.evidence_grade.in_(DECISIVE_REVIEW_STATUSES)
                )
            )
        )
        scored: list[tuple[float, PlatformKnowledgeItem]] = []
        for item in items:
            if not self._matches_filter(category, item.applicable_categories_json):
                continue
            if not self._matches_filter(stage, item.business_stages_json):
                continue
            if not self._matches_filter(region, item.regions_json):
                continue
            score = self._score(query, item.content, item.tags_json)
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda pair: (-pair[0], pair[1].id))
        return [
            KnowledgeHit(
                id=item.id,
                scope="platform",
                source_type=item.source_type,
                source_id=item.source_id,
                source_uri=item.source_uri,
                knowledge_id=item.knowledge_id,
                version=item.version,
                kind=item.kind,
                content=item.content,
                tags=item.tags_json,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                score=score,
                review_status=item.review_status,
                evidence_grade=item.evidence_grade,
            )
            for score, item in scored[:limit]
        ]

    @staticmethod
    def _matches_filter(value: str | None, allowed: list[str]) -> bool:
        if value is None or not allowed:
            return True
        normalized = value.casefold().strip()
        return any(normalized == item.casefold().strip() for item in allowed)

    @staticmethod
    def _score(query: str, content: str, tags: list[str]) -> float:
        score = KnowledgeService._score(query, content, tags)
        normalized_query = "".join(query.casefold().split())
        searchable = f"{content} {' '.join(tags)}".casefold()
        if len(normalized_query) >= 2:
            bigrams = {
                normalized_query[index : index + 2]
                for index in range(len(normalized_query) - 1)
            }
            score += sum(1.0 for token in bigrams if token in searchable)
        return score


