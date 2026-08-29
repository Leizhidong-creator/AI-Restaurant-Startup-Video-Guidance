from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import (
    AsyncDecisionRuntime,
    AsyncToolRegistry,
    Conclusion,
    DecisionRuntime,
    EvidenceKind,
    NextAction,
    SessionSnapshot,
    Stage,
    ToolName,
    ToolRegistry,
    ToolResult,
    ToolStatus,
    RestaurantSkillProvider,
    calculate_business_metrics,
)


def full_facts():
    return {
        "payment_or_signature_within_72h": False,
        "deposit_paid": False,
        "funding_type": "自有",
        "borrowed_amount": 0,
        "maximum_affordable_loss": 100000,
        "location": "上海示例路1号",
        "scene_type": "场馆内街",
        "category": "面馆",
        "target_period": "工作日午餐",
        "monthly_rent": 6000,
        "transfer_fee": 0,
        "store_area_sqm": 84,
        "monthly_labor_cost": 21000,
        "monthly_other_fixed_cost": 4000,
        "operating_days_per_month": 30,
        "expected_daily_revenue": 1800,
        "revenue_basis": "蹲点记录",
        "contribution_margin_rate": 0.6,
        "site_media_refs": ["private://video"],
    }


def ok(evidence_id: str, data=None, source="test:v1") -> ToolResult:
    return ToolResult(
        status=ToolStatus.OK,
        evidence_ids=(evidence_id,),
        data=data or {"value": 1},
        source=source,
    )


class RuntimeTest(unittest.TestCase):
    def test_runtime_executes_tools_until_judgment_boundary(self) -> None:
        registry = ToolRegistry(
            {
                ToolName.BUSINESS_CALCULATION: calculate_business_metrics,
                ToolName.VISUAL_ANALYSIS: lambda arguments: ok(
                    "visual:1", {"observations": [{"observation": "门头朝内"}]}
                ),
                ToolName.PLATFORM_RAG: lambda arguments: ToolResult(
                    status=ToolStatus.NO_HIT,
                    source="rag:test",
                ),
                ToolName.AMAP_COMPETITORS: lambda arguments: ok("amap:1"),
            }
        )
        runtime = DecisionRuntime(RestaurantSkillProvider(), registry)
        result = runtime.advance(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=full_facts())
        )
        self.assertEqual(result.directive.action, NextAction.READY_FOR_JUDGMENT)
        self.assertIn(Conclusion.DO_NOT_PROCEED, result.directive.allowed_conclusions)
        self.assertEqual(len(result.trace), 5)
        self.assertEqual(
            [event.directive.tool_name for event in result.trace[:-1]],
            [
                ToolName.BUSINESS_CALCULATION,
                ToolName.VISUAL_ANALYSIS,
                ToolName.PLATFORM_RAG,
                ToolName.AMAP_COMPETITORS,
            ],
        )

    def test_runtime_stops_at_question_without_calling_tools(self) -> None:
        runtime = DecisionRuntime(RestaurantSkillProvider(), ToolRegistry())
        result = runtime.advance(SessionSnapshot(stage=Stage.PLANNED_OPENING, facts={}))
        self.assertEqual(result.directive.action, NextAction.ASK)
        self.assertEqual(len(result.trace), 1)

    def test_unregistered_critical_tools_reduce_conclusion(self) -> None:
        registry = ToolRegistry(
            {
                ToolName.PLATFORM_RAG: lambda arguments: ToolResult(
                    status=ToolStatus.NO_HIT,
                    source="rag:test",
                )
            }
        )
        result = DecisionRuntime(RestaurantSkillProvider(), registry).advance(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=full_facts())
        )
        self.assertEqual(
            result.directive.allowed_conclusions,
            (Conclusion.INSUFFICIENT_EVIDENCE,),
        )
        self.assertEqual(len(result.trace), 2)

    def test_registry_rejects_duplicate_tool(self) -> None:
        registry = ToolRegistry({ToolName.PLATFORM_RAG: lambda arguments: ok("rag:1")})
        with self.assertRaises(ValueError):
            registry.register(ToolName.PLATFORM_RAG, lambda arguments: ok("rag:2"))

    def test_registry_rejects_non_contract_result(self) -> None:
        registry = ToolRegistry({ToolName.PLATFORM_RAG: lambda arguments: {}})
        with self.assertRaises(TypeError):
            registry.run(ToolName.PLATFORM_RAG, {})

    def test_confirmed_store_profile_hydrates_missing_facts(self) -> None:
        registry = ToolRegistry(
            {
                ToolName.STORE_PROFILE: lambda arguments: ok(
                    "profile:store-1:2",
                    {"facts": full_facts()},
                    source="store-profile:test",
                )
            }
        )
        result = DecisionRuntime(RestaurantSkillProvider(), registry).advance(
            SessionSnapshot(
                stage=Stage.PLANNED_OPENING,
                facts={
                    "payment_or_signature_within_72h": False,
                    "deposit_paid": False,
                    "funding_type": "自有",
                },
                user_id="user-1",
                store_id="store-1",
            )
        )
        rent = result.snapshot.fact("monthly_rent")
        self.assertIsNotNone(rent)
        self.assertEqual(rent.value, 6000)
        self.assertEqual(rent.kind, EvidenceKind.TOOL)
        self.assertEqual(result.trace[0].directive.tool_name, ToolName.STORE_PROFILE)

    def test_store_profile_does_not_overwrite_current_session_fact(self) -> None:
        registry = ToolRegistry(
            {
                ToolName.STORE_PROFILE: lambda arguments: ok(
                    "profile:store-1:2",
                    {"facts": full_facts()},
                    source="store-profile:test",
                )
            }
        )
        current = {
            "payment_or_signature_within_72h": False,
            "deposit_paid": False,
            "funding_type": "自有",
            "monthly_rent": 7000,
        }
        result = DecisionRuntime(RestaurantSkillProvider(), registry).advance(
            SessionSnapshot(
                stage=Stage.PLANNED_OPENING,
                facts=current,
                user_id="user-1",
                store_id="store-1",
            )
        )
        self.assertEqual(result.snapshot.value("monthly_rent"), 7000)


class AsyncRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_runtime_supports_realtime_backends(self) -> None:
        async def platform_rag(arguments):
            return ToolResult(status=ToolStatus.NO_HIT, source="rag:async-test")

        runtime = AsyncDecisionRuntime(
            RestaurantSkillProvider(),
            AsyncToolRegistry({ToolName.PLATFORM_RAG: platform_rag}),
        )
        result = await runtime.advance(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=full_facts())
        )
        self.assertEqual(len(result.trace), 2)
        self.assertEqual(result.trace[0].directive.tool_name, ToolName.PLATFORM_RAG)
        self.assertEqual(
            result.directive.allowed_conclusions,
            (Conclusion.INSUFFICIENT_EVIDENCE,),
        )


if __name__ == "__main__":
    unittest.main()


