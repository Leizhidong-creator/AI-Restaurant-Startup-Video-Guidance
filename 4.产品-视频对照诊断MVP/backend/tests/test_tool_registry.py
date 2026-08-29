import pytest

from yongge_online.core.errors import DomainError
from yongge_online.tools.map_provider import UnavailableMapProvider
from yongge_online.tools.registry import ToolRegistry
from yongge_online.tools.schemas import StoreSnapshot


class FakeRetriever:
    async def search(self, *, user_id: str, store_id: str, query: str, limit: int):
        assert user_id == "user-1"
        assert store_id == "store-1"
        assert query == "房租风险"
        assert limit == 3
        return [
            {
                "id": "knowledge-1",
                "kind": "risk",
                "content": "高房租会持续侵蚀现金流。",
                "tags": ["房租"],
                "score": 11.0,
                "start_ms": None,
                "end_ms": None,
            }
        ]


class FakePlatformRetriever:
    async def search(
        self,
        *,
        query: str,
        limit: int,
        category: str | None = None,
        stage: str | None = None,
        region: str | None = None,
    ):
        assert query == "奶茶选址"
        assert limit == 2
        assert category == "奶茶"
        assert stage == "planning"
        assert region == "武汉"
        return [
            {
                "id": "platform-rule-1",
                "scope": "platform",
                "source_type": "expert_video",
                "source_id": "video-1",
                "kind": "rule",
                "content": "先验证目标时段客流，再决定是否签约。",
                "tags": ["选址"],
                "score": 0.92,
                "start_ms": 1200,
                "end_ms": 8600,
                "review_status": "reviewed",
            }
        ]


@pytest.mark.asyncio
async def test_registry_executes_private_knowledge_and_map_fallback() -> None:
    registry = ToolRegistry(
        store=StoreSnapshot(
            id="store-1",
            user_id="user-1",
            name="测试店",
            category="奶茶",
            stage="operating",
            longitude=114.40,
            latitude=30.50,
        ),
        retriever=FakeRetriever(),
        map_provider=UnavailableMapProvider("未配置高德 Web 服务 Key"),
    )

    knowledge = await registry.execute(
        "retrieve_private_knowledge",
        {"query": "房租风险", "limit": 3},
    )
    assert knowledge["hits"][0]["id"] == "knowledge-1"

    map_result = await registry.execute(
        "search_nearby_competitors",
        {"radius_m": 1000},
    )
    assert map_result["available"] is False
    assert "高德" in map_result["reason"]
    assert map_result["competitors"] == []


@pytest.mark.asyncio
async def test_registry_rejects_unknown_tool() -> None:
    registry = ToolRegistry(
        store=StoreSnapshot(
            id="store-1",
            user_id="user-1",
            name="测试店",
            category="奶茶",
            stage="operating",
        ),
        retriever=FakeRetriever(),
        map_provider=UnavailableMapProvider("missing key"),
    )

    with pytest.raises(DomainError) as error:
        await registry.execute("delete_everything", {})

    assert error.value.code == "unknown_tool"


@pytest.mark.asyncio
async def test_registry_executes_platform_rag_with_stable_evidence_ids() -> None:
    registry = ToolRegistry(
        store=StoreSnapshot(
            id="store-1",
            user_id="user-1",
            name="测试店",
            category="奶茶",
            stage="planning",
        ),
        retriever=FakeRetriever(),
        platform_retriever=FakePlatformRetriever(),
        map_provider=UnavailableMapProvider("missing key"),
    )

    result = await registry.execute(
        "platform_rag",
        {
            "query": "奶茶选址",
            "limit": 2,
            "category": "奶茶",
            "stage": "planning",
            "region": "武汉",
        },
    )

    assert result["status"] == "ok"
    assert result["evidence_ids"] == ["platform-rule-1"]
    assert result["source"] == "platform_knowledge"
    assert result["data"]["hits"][0]["id"] == "platform-rule-1"


@pytest.mark.asyncio
async def test_business_metrics_accepts_numbers_supplied_during_call() -> None:
    registry = ToolRegistry(
        store=StoreSnapshot(
            id="store-1",
            user_id="user-1",
            name="还在筹备的店",
            category="奶茶",
            stage="planning",
        ),
        retriever=FakeRetriever(),
        map_provider=UnavailableMapProvider("missing key"),
    )

    result = await registry.execute(
        "calculate_business_metrics",
        {
            "monthly_rent": 10000,
            "monthly_labor_cost": 9000,
            "monthly_other_fixed_cost": 2000,
            "ingredient_cost_rate": 0.35,
            "operating_days_per_month": 30,
        },
    )

    assert result["available"] is True
    assert result["break_even_monthly_revenue"] == "32307.69"
    assert result["break_even_daily_revenue"] == "1076.92"


@pytest.mark.asyncio
async def test_general_calculator_executes_deterministic_arithmetic() -> None:
    registry = ToolRegistry(
        store=StoreSnapshot(
            id="store-1",
            user_id="user-1",
            name="还在筹备的店",
            category="奶茶",
            stage="planning",
        ),
        retriever=FakeRetriever(),
        map_provider=UnavailableMapProvider("missing key"),
    )

    result = await registry.execute(
        "calculate",
        {
            "expression": "investment / monthly_profit",
            "variables": {"investment": 80000, "monthly_profit": 10000},
            "unit": "个月",
        },
    )

    assert result["available"] is True
    assert result["result"] == "8"
    assert result["unit"] == "个月"


