from typing import Any

from pydantic import ValidationError

from yongge_online.core.errors import DomainError
from yongge_online.knowledge.ports import (
    KnowledgeRetrieverPort,
    PlatformKnowledgeRetrieverPort,
)
from yongge_online.tools.business import calculate_business_metrics, calculate_expression
from yongge_online.tools.map_provider import MapProviderPort
from yongge_online.tools.schemas import (
    BusinessMetricsInput,
    CalculatorInput,
    KnowledgeQuery,
    MapQuery,
    PlatformKnowledgeQuery,
    StoreSnapshot,
)


class ToolRegistry:
    def __init__(
        self,
        *,
        store: StoreSnapshot,
        retriever: KnowledgeRetrieverPort,
        platform_retriever: PlatformKnowledgeRetrieverPort | None = None,
        map_provider: MapProviderPort,
    ):
        self.store = store
        self.retriever = retriever
        self.platform_retriever = platform_retriever
        self.map_provider = map_provider

    @property
    def definitions(self) -> list[dict[str, Any]]:
        return [
            self._definition("get_store_profile", "读取当前门店结构化档案", {}),
            self._definition(
                "calculate",
                "通用确定性计算器。凡涉及加减乘除、比例、差额、回本周期、客单价与客流换算等算术都应调用；只执行给定公式，不替模型补业务假设",
                {
                    "expression": {
                        "type": "string",
                        "description": "仅含数字、变量、括号和加减乘除的算式，例如 investment / monthly_profit",
                    },
                    "variables": {
                        "type": "object",
                        "description": "算式中的变量和值",
                        "additionalProperties": {"type": "number"},
                    },
                    "unit": {
                        "type": "string",
                        "description": "结果单位，例如 元、%、个月、单/天",
                    },
                },
                required=["expression"],
            ),
            self._definition(
                "calculate_business_metrics",
                "标准单店经营测算：用门店档案和用户本轮提供的数字，计算营业额、成本、毛利、利润、保本线和安全边际；参数会覆盖档案旧值",
                {
                    "monthly_revenue": {
                        "type": "number",
                        "minimum": 0,
                        "description": "当前月营收；只算保本点时可不填",
                    },
                    "monthly_rent": {"type": "number", "minimum": 0, "description": "月租金"},
                    "monthly_labor_cost": {
                        "type": "number",
                        "minimum": 0,
                        "description": "每月人工成本",
                    },
                    "monthly_other_fixed_cost": {
                        "type": "number",
                        "minimum": 0,
                        "description": "每月水电、物业等其他固定成本",
                    },
                    "ingredient_cost_rate": {
                        "type": "number",
                        "minimum": 0,
                        "exclusiveMaximum": 1,
                        "description": "食材成本率，用小数表示，例如 35% 填 0.35",
                    },
                    "operating_days_per_month": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 31,
                        "description": "每月营业天数，默认 30",
                    },
                },
            ),
            self._definition(
                "platform_rag",
                "检索经过审核的平台餐饮专家知识、判断规则和真实案例",
                {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                    "category": {"type": "string"},
                    "stage": {"type": "string"},
                    "region": {"type": "string"},
                },
                required=["query"],
            ),
            self._definition(
                "retrieve_private_knowledge",
                "检索用户上传资料中与问题相关的知识和证据",
                {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                required=["query"],
            ),
            self._definition(
                "search_nearby_competitors",
                "查询门店周边同类餐饮竞品；不可用时返回明确原因",
                {
                    "radius_m": {
                        "type": "integer",
                        "minimum": 100,
                        "maximum": 5000,
                    }
                },
            ),
        ]

    @staticmethod
    def _definition(
        name: str,
        description: str,
        properties: dict[str, Any],
        *,
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                    "additionalProperties": False,
                },
            },
        }

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            if tool_name == "get_store_profile":
                return self.store.model_dump(mode="json")
            if tool_name == "calculate":
                supplied = CalculatorInput.model_validate(arguments)
                return calculate_expression(
                    expression=supplied.expression,
                    variables=supplied.variables,
                    unit=supplied.unit,
                )
            if tool_name == "calculate_business_metrics":
                supplied = BusinessMetricsInput.model_validate(arguments)
                store = self.store.model_copy(
                    update=supplied.model_dump(exclude_none=True)
                )
                return calculate_business_metrics(store).model_dump(mode="json")
            if tool_name == "retrieve_private_knowledge":
                query = KnowledgeQuery.model_validate(arguments)
                hits = await self.retriever.search(
                    user_id=self.store.user_id or "",
                    store_id=self.store.id,
                    query=query.query,
                    limit=query.limit,
                )
                return {
                    "hits": [
                        hit.model_dump(mode="json") if hasattr(hit, "model_dump") else hit
                        for hit in hits
                    ]
                }
            if tool_name == "platform_rag":
                query = PlatformKnowledgeQuery.model_validate(arguments)
                if self.platform_retriever is None:
                    return {
                        "status": "unavailable",
                        "evidence_ids": [],
                        "data": {"hits": []},
                        "source": "platform_knowledge",
                        "error_code": "platform_retriever_not_configured",
                    }
                hits = await self.platform_retriever.search(
                    query=query.query,
                    limit=query.limit,
                    category=query.category,
                    stage=query.stage,
                    region=query.region,
                )
                serialized = [
                    hit.model_dump(mode="json") if hasattr(hit, "model_dump") else hit
                    for hit in hits
                ]
                evidence_ids = [str(hit["id"]) for hit in serialized if hit.get("id")]
                return {
                    "status": "ok" if serialized else "no_hit",
                    "evidence_ids": evidence_ids,
                    "data": {"hits": serialized},
                    "source": "platform_knowledge",
                    "error_code": None,
                }
            if tool_name == "search_nearby_competitors":
                query = MapQuery.model_validate(arguments)
                if self.store.longitude is None or self.store.latitude is None:
                    return {
                        "available": False,
                        "reason": "门店缺少经纬度，无法查询周边竞品",
                        "radius_m": query.radius_m,
                        "competitors": [],
                    }
                result = await self.map_provider.nearby_competitors(
                    longitude=float(self.store.longitude),
                    latitude=float(self.store.latitude),
                    category=self.store.category,
                    radius_m=query.radius_m,
                )
                return result.model_dump(mode="json")
        except ValidationError as exc:
            raise DomainError(
                f"工具参数不合法：{exc}",
                code="invalid_tool_arguments",
                status_code=422,
            ) from exc
        raise DomainError(
            f"不允许调用工具：{tool_name}",
            code="unknown_tool",
            status_code=422,
        )


