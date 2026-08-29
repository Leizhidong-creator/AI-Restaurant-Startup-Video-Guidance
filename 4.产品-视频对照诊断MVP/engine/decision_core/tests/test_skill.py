from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import (
    Conclusion,
    NextAction,
    QuestionSelection,
    SessionSnapshot,
    Stage,
    ToolName,
    RestaurantSkillProvider,
)


class SelectLastPlanner:
    def select(self, snapshot, candidates):
        chosen = candidates[-1]
        return QuestionSelection(chosen.fact_key, chosen.question, "test-model-selection")


def planned_facts():
    return {
        "payment_or_signature_within_72h": False,
        "deposit_paid": False,
        "funding_type": "自有",
        "borrowed_amount": 0,
        "maximum_affordable_loss": 100000,
        "location": "上海市示例路1号",
        "scene_type": "体育场馆内街",
        "category": "面馆",
        "target_period": "工作日11:00-13:00",
        "monthly_rent": 6000,
        "transfer_fee": 0,
        "store_area_sqm": 84,
        "monthly_labor_cost": 21000,
        "monthly_other_fixed_cost": 4000,
        "operating_days_per_month": 30,
        "expected_daily_revenue": 1800,
        "revenue_basis": "现场蹲点和竞品出单记录",
        "contribution_margin_rate": 0.6,
        "site_media_refs": ["private://site-video-1"],
    }


def ok_result(evidence_id, data=None, source="test:v1"):
    return {
        "status": "ok",
        "evidence_ids": [evidence_id],
        "data": data or {"value": 1},
        "source": source,
    }


class SkillPolicyTest(unittest.TestCase):
    def test_planned_opening_starts_with_structured_irreversible_gate(self) -> None:
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts={})
        )
        self.assertEqual(directive.action, NextAction.ASK)
        self.assertEqual(directive.missing_facts[0], "payment_or_signature_within_72h")

    def test_semantic_planner_selects_question_instead_of_list_order(self) -> None:
        facts = {
            "payment_or_signature_within_72h": False,
            "deposit_paid": False,
            "funding_type": "自有",
        }
        directive = RestaurantSkillProvider(question_planner=SelectLastPlanner()).next_directive(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=facts)
        )
        self.assertEqual(directive.action, NextAction.ASK)
        self.assertEqual(directive.rationale_codes[-1], "contribution_margin_rate")

    def test_missing_model_planner_is_explicit_not_fake_dynamic(self) -> None:
        facts = {
            "payment_or_signature_within_72h": False,
            "deposit_paid": False,
            "funding_type": "自有",
        }
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=facts)
        )
        self.assertEqual(directive.action, NextAction.PLAN_QUESTION)
        self.assertGreater(len(directive.question_candidates), 1)

    def test_negative_prose_does_not_trigger_keyword_warning(self) -> None:
        facts = {
            "payment_or_signature_within_72h": False,
            "deposit_paid": False,
            "funding_type": "没有贷款，全部是自有资金",
        }
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=facts)
        )
        self.assertIsNone(directive.warning)

    def test_structured_leverage_adds_pause_warning(self) -> None:
        facts = {
            "payment_or_signature_within_72h": True,
            "deposit_paid": False,
            "funding_type": "贷款",
        }
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=facts)
        )
        self.assertIn("暂停", directive.warning or "")

    def test_capture_is_requested_before_tools(self) -> None:
        facts = planned_facts()
        facts.pop("site_media_refs")
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=facts)
        )
        self.assertEqual(directive.action, NextAction.REQUEST_CAPTURE)
        self.assertEqual(len(directive.tool_arguments["checklist"]), 6)

    def test_capture_does_not_wait_for_every_financial_fact(self) -> None:
        facts = {
            "payment_or_signature_within_72h": False,
            "deposit_paid": False,
            "funding_type": "自有",
            "location": "上海市示例路1号",
            "category": "面馆",
            "target_period": "工作日11:00-13:00",
        }
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=facts)
        )
        self.assertEqual(directive.action, NextAction.REQUEST_CAPTURE)
        self.assertIn("monthly_rent", directive.missing_facts)

    def test_ready_tool_is_called_before_more_questions(self) -> None:
        facts = {
            "payment_or_signature_within_72h": False,
            "deposit_paid": False,
            "funding_type": "自有",
            "category": "面馆",
            "site_media_refs": ["private://site-video-1"],
        }
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(
                stage=Stage.PLANNED_OPENING,
                facts=facts,
                available_tools=frozenset({ToolName.PLATFORM_RAG}),
            )
        )
        self.assertEqual(directive.action, NextAction.CALL_TOOL)
        self.assertEqual(directive.tool_name, ToolName.PLATFORM_RAG)
        self.assertIn("monthly_rent", directive.missing_facts)

    def test_confirmed_store_profile_is_loaded_before_reasking_facts(self) -> None:
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(
                stage=Stage.PLANNED_OPENING,
                facts={
                    "payment_or_signature_within_72h": False,
                    "deposit_paid": False,
                    "funding_type": "自有",
                },
                user_id="user-1",
                store_id="store-1",
                available_tools=frozenset({ToolName.STORE_PROFILE}),
            )
        )
        self.assertEqual(directive.action, NextAction.CALL_TOOL)
        self.assertEqual(directive.tool_name, ToolName.STORE_PROFILE)
        self.assertEqual(
            directive.tool_arguments,
            {"user_id": "user-1", "store_id": "store-1"},
        )

    def test_calculator_receives_complete_atomic_inputs(self) -> None:
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(
                stage=Stage.PLANNED_OPENING,
                facts=planned_facts(),
                available_tools=frozenset({ToolName.BUSINESS_CALCULATION}),
            )
        )
        self.assertEqual(directive.action, NextAction.CALL_TOOL)
        self.assertEqual(directive.tool_name, ToolName.BUSINESS_CALCULATION)
        self.assertEqual(directive.tool_arguments["expected_daily_revenue"], 1800)
        self.assertEqual(directive.tool_arguments["operating_days_per_month"], 30)
        self.assertEqual(directive.tool_arguments["monthly_other_fixed_cost"], 4000)

    def test_empty_tool_results_cannot_pass_evidence_gate(self) -> None:
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(
                stage=Stage.PLANNED_OPENING,
                facts=planned_facts(),
                tool_results={
                    ToolName.BUSINESS_CALCULATION: {},
                    ToolName.VISUAL_ANALYSIS: {},
                    ToolName.PLATFORM_RAG: {},
                    ToolName.AMAP_COMPETITORS: {},
                },
            )
        )
        self.assertEqual(directive.action, NextAction.READY_FOR_JUDGMENT)
        self.assertEqual(directive.allowed_conclusions, (Conclusion.INSUFFICIENT_EVIDENCE,))

    def test_ready_requires_valid_critical_evidence(self) -> None:
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(
                stage=Stage.PLANNED_OPENING,
                facts=planned_facts(),
                tool_results={
                    ToolName.BUSINESS_CALCULATION: ok_result(
                        "calc:1", {"break_even_daily_revenue": 1722}
                    ),
                    ToolName.VISUAL_ANALYSIS: ok_result(
                        "visual:1", {"observations": [{"observation": "门头朝内"}]}
                    ),
                    ToolName.PLATFORM_RAG: ok_result("rag:1"),
                    ToolName.AMAP_COMPETITORS: ok_result("amap:1"),
                },
            )
        )
        self.assertEqual(directive.action, NextAction.READY_FOR_JUDGMENT)
        self.assertIn(Conclusion.DO_NOT_PROCEED, directive.allowed_conclusions)
        self.assertNotIn(Conclusion.INSUFFICIENT_EVIDENCE, directive.allowed_conclusions)

    def test_franchise_current_lookup_is_critical(self) -> None:
        facts = {
            "payment_or_signature_within_72h": False,
            "deposit_paid": False,
            "funding_type": "自有",
            "borrowed_amount": 0,
            "maximum_affordable_loss": 100000,
            "brand_name": "示例品牌",
            "contract_company_name": "示例公司",
            "franchise_fee": "加盟5万、设备8万、装修7万",
            "direct_store_evidence": "两家直营店实地记录",
            "contract_exit_terms": "已提供退出条款",
            "location": "示例路1号",
            "category": "奶茶",
        }
        directive = RestaurantSkillProvider().next_directive(
            SessionSnapshot(
                stage=Stage.FRANCHISE,
                facts=facts,
                tool_results={ToolName.PLATFORM_RAG: {"status": "no_hit", "source": "rag:v1"}},
            )
        )
        self.assertEqual(directive.allowed_conclusions, (Conclusion.INSUFFICIENT_EVIDENCE,))
        self.assertIn(ToolName.CURRENT_BUSINESS_LOOKUP, directive.unavailable_tools)


if __name__ == "__main__":
    unittest.main()


