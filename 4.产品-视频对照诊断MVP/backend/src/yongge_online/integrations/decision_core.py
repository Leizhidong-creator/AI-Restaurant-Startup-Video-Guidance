import asyncio
from collections.abc import Callable
from typing import Any, Protocol

from yongge_online.knowledge.schemas import KnowledgeHit
from yongge_online.skills.ports import (
    SkillAdvanceResult,
    SkillContext,
    SkillSessionContext,
)


class AsyncDecisionRuntimeLike(Protocol):
    async def advance(self, snapshot: Any) -> Any: ...


class ScopedVectorRetrieverLike(Protocol):
    def search(self, query: str, **kwargs: Any) -> list[Any]: ...


class DecisionCoreSkillEngineAdapter:
    """Bind AsyncDecisionRuntime to the backend SkillEnginePort without vendoring it."""

    def __init__(
        self,
        *,
        runtime: AsyncDecisionRuntimeLike,
        snapshot_builder: Callable[[SkillSessionContext], Any],
        instruction_builder: Callable[[SkillContext], str],
    ) -> None:
        self.runtime = runtime
        self.snapshot_builder = snapshot_builder
        self.instruction_builder = instruction_builder

    async def build_session_instructions(self, context: SkillContext) -> str:
        return self.instruction_builder(context)

    async def advance(self, context: SkillSessionContext) -> SkillAdvanceResult:
        snapshot = self.snapshot_builder(context)
        runtime_result = await self.runtime.advance(snapshot)
        value = (
            runtime_result.to_dict()
            if hasattr(runtime_result, "to_dict")
            else runtime_result
        )
        return SkillAdvanceResult.model_validate(value)


class DecisionCorePlatformRetrieverAdapter:
    """Expose ScopedVectorRetriever as the async platform knowledge Port."""

    source = "decision_core_scoped_vector"

    def __init__(
        self,
        retriever: ScopedVectorRetrieverLike,
        *,
        minimum_evidence_grade: str = "reviewed",
    ) -> None:
        self.retriever = retriever
        self.minimum_evidence_grade = minimum_evidence_grade

    async def search(
        self,
        *,
        query: str,
        limit: int,
        category: str | None = None,
        stage: str | None = None,
        region: str | None = None,
    ) -> list[KnowledgeHit]:
        qualifiers = [query]
        if category:
            qualifiers.append(f"品类：{category}")
        if region:
            qualifiers.append(f"地区：{region}")
        search_query = "\n".join(qualifiers)
        hits = await asyncio.to_thread(
            self.retriever.search,
            search_query,
            scope="platform",
            top_k=limit,
            stages=(stage,) if stage else (),
            minimum_evidence_grade=self.minimum_evidence_grade,
        )
        return [
            KnowledgeHit(
                id=str(hit.evidence_id),
                scope="platform",
                source_type="platform_rag",
                source_id=str(hit.knowledge_id),
                source_uri=str(hit.source_url) if hit.source_url else None,
                kind="knowledge",
                content=str(hit.snippet),
                tags=[
                    str(hit.title),
                    str(hit.evidence_grade),
                    str(hit.retrieval_mode),
                ],
                start_ms=None,
                end_ms=None,
                score=float(hit.score),
                review_status=str(hit.review_status),
                knowledge_id=str(hit.knowledge_id),
                evidence_grade=str(hit.evidence_grade),
            )
            for hit in hits
        ]


