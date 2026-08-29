from types import SimpleNamespace

import pytest

from yongge_online.integrations.decision_core import (
    DecisionCorePlatformRetrieverAdapter,
    DecisionCoreSkillEngineAdapter,
)
from yongge_online.skills.ports import SkillContext, SkillSessionContext
from yongge_online.tools.schemas import StoreSnapshot


def build_store() -> StoreSnapshot:
    return StoreSnapshot(
        id="store-1",
        user_id="user-1",
        name="适配器测试店",
        category="奶茶",
        stage="planning",
    )


class FakeRuntimeResult:
    def to_dict(self):
        return {
            "directive": {
                "action": "request_capture",
                "message": "请退后两步拍摄门头。",
                "missing_facts": [],
                "question_candidates": [],
                "tool_name": None,
                "tool_arguments": {},
                "allowed_conclusions": [],
                "warning": None,
                "unavailable_tools": [],
                "rationale_codes": ["verify_storefront_visibility"],
            },
            "tool_results": {},
            "trace": [{"sequence": 1}],
        }


class FakeAsyncDecisionRuntime:
    def __init__(self) -> None:
        self.snapshot = None

    async def advance(self, snapshot):
        self.snapshot = snapshot
        return FakeRuntimeResult()


@pytest.mark.asyncio
async def test_skill_adapter_passes_backend_context_to_async_decision_runtime() -> None:
    runtime = FakeAsyncDecisionRuntime()
    adapter = DecisionCoreSkillEngineAdapter(
        runtime=runtime,
        snapshot_builder=lambda context: {"session_id": context.session_id},
        instruction_builder=lambda context: f"决策项目：{context.store.name}",
    )
    context = SkillSessionContext(
        session_id="session-1",
        user_id="user-1",
        store=build_store(),
        facts={},
        evidence={},
        hypotheses=[],
        events=[],
        tool_calls=[],
        has_private_knowledge=False,
    )

    instructions = await adapter.build_session_instructions(
        SkillContext(session_id="session-1", store=build_store())
    )
    result = await adapter.advance(context)

    assert instructions == "决策项目：适配器测试店"
    assert runtime.snapshot == {"session_id": "session-1"}
    assert result.directive.action == "request_capture"
    assert result.trace == [{"sequence": 1}]


class FakeScopedVectorRetriever:
    def __init__(self) -> None:
        self.call = None

    def search(self, query, **kwargs):
        self.call = {"query": query, **kwargs}
        return [
            SimpleNamespace(
                evidence_id="rag:platform:method-site-001:2.0",
                knowledge_id="method-site-001",
                title="先验证目标时段客流",
                snippet="签约前在目标时段观察客流和门头可见性。",
                score=0.88,
                source_url="https://example.test/source",
                source_locator="video:1200-8600",
                published_at="2026-07-01",
                review_status="reviewed-2026-07-20",
                evidence_grade="reviewed",
                retrieval_mode="dense_vector",
            )
        ]


@pytest.mark.asyncio
async def test_platform_adapter_maps_scoped_vector_hits_to_backend_evidence() -> None:
    retriever = FakeScopedVectorRetriever()
    adapter = DecisionCorePlatformRetrieverAdapter(retriever)

    hits = await adapter.search(
        query="奶茶店选址",
        limit=3,
        category="奶茶",
        stage="planned_opening",
        region="武汉",
    )

    assert retriever.call == {
        "query": "奶茶店选址\n品类：奶茶\n地区：武汉",
        "scope": "platform",
        "top_k": 3,
        "stages": ("planned_opening",),
        "minimum_evidence_grade": "reviewed",
    }
    assert hits[0].id == "rag:platform:method-site-001:2.0"
    assert hits[0].scope == "platform"
    assert hits[0].source_id == "method-site-001"
    assert hits[0].content == "签约前在目标时段观察客流和门头可见性。"
    assert hits[0].score == 0.88


