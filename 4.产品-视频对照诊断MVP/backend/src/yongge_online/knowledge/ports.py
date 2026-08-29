from typing import Protocol

from yongge_online.knowledge.schemas import KnowledgeHit


class KnowledgeRetrieverPort(Protocol):
    async def search(
        self,
        *,
        user_id: str,
        store_id: str,
        query: str,
        limit: int,
    ) -> list[KnowledgeHit] | list[dict]: ...


class PlatformKnowledgeRetrieverPort(Protocol):
    async def search(
        self,
        *,
        query: str,
        limit: int,
        category: str | None = None,
        stage: str | None = None,
        region: str | None = None,
    ) -> list[KnowledgeHit] | list[dict]: ...


