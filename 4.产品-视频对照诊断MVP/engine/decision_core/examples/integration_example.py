from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import (
    CallableEvidenceTool,
    CallableVisionAnalyzer,
    Conclusion,
    DecisionRuntime,
    Judgment,
    LexicalFallbackRetriever,
    NextAction,
    SessionSnapshot,
    Stage,
    ToolName,
    ToolRegistry,
    RestaurantSkillProvider,
    calculate_business_metrics,
    retrieval_hits_to_result,
    validate_judgment,
)


FACTS = {
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
    "site_media_refs": ["private://demo/site-video-1"],
}


def demo_visual_model(media_refs, prompt):
    """Deterministic fixture for wiring only; replace with a real multimodal model."""

    return {
        "coverage_codes": ["front", "left", "right", "opposite", "entrance", "parking"],
        "observations": [
            {
                "observation": "铺位位于场馆主入口转弯后的内街",
                "frame_locator": "00:18",
                "confidence": 0.96,
            }
        ],
        "inferences": [
            {
                "inference": "自然曝光可能弱于入口正对铺位",
                "supporting_frame_locators": ["00:18"],
                "confidence": 0.72,
            }
        ],
        "missing_captures": [],
    }


def build_runtime() -> DecisionRuntime:
    visual = CallableVisionAnalyzer(demo_visual_model, model_name="demo-fixture-not-live")
    platform = LexicalFallbackRetriever(ROOT / "knowledge" / "platform.jsonl")
    amap = CallableEvidenceTool(
        lambda arguments: {
            "status": "ok",
            "evidence_ids": ["amap:demo:example-road-noodle:1"],
            "data": {"pois": [{"name": "示例面馆", "distance_m": 420}]},
        },
        source="demo-amap-fixture:not-live",
        required_arguments=("location", "category"),
    )
    registry = ToolRegistry(
        {
            ToolName.BUSINESS_CALCULATION: calculate_business_metrics,
            ToolName.VISUAL_ANALYSIS: lambda arguments: visual.analyze(
                arguments["media_refs"],
                stage=arguments["stage"],
                category=arguments["category"],
                target_period=arguments["target_period"],
            ),
            ToolName.PLATFORM_RAG: lambda arguments: retrieval_hits_to_result(
                platform.search(
                    arguments["query"],
                    scope="platform",
                    top_k=arguments["top_k"],
                    minimum_evidence_grade=arguments["minimum_evidence_grade"],
                ),
                source="platform-rag:lexical-fallback",
            ),
            ToolName.AMAP_COMPETITORS: amap.run,
        }
    )
    return DecisionRuntime(RestaurantSkillProvider(), registry)


def main() -> int:
    result = build_runtime().advance(
        SessionSnapshot(stage=Stage.PLANNED_OPENING, facts=FACTS)
    )
    if result.directive.action != NextAction.READY_FOR_JUDGMENT:
        raise RuntimeError(f"unexpected boundary: {result.directive.action.value}")
    calculation = result.snapshot.result(ToolName.BUSINESS_CALCULATION)
    visual = result.snapshot.result(ToolName.VISUAL_ANALYSIS)
    if calculation is None or visual is None:
        raise RuntimeError("critical evidence missing from completed runtime trace")

    judgment = Judgment(
        conclusion=Conclusion.PROCEED_WITH_CONDITIONS,
        confidence=0.68,
        decisive_evidence_ids=(*calculation.evidence_ids, *visual.evidence_ids),
        counter_evidence_ids=(),
        critical_gap="场馆工作日午餐的实际有效客流仍需连续三天验证",
        first_action="连续三个工作日记录入口经过、目标客群、进店和竞品出单",
        verification_condition="实测营业额可稳定覆盖计算得到的保本日营业额",
        stop_condition="三天有效客流明显不足且入口曝光无法整改",
        assumptions=("高德结果为离线演示夹具，不能作为真实位置结论",),
    )
    errors = validate_judgment(
        judgment,
        result.snapshot,
        allowed_conclusions=result.directive.allowed_conclusions,
    )
    output = result.to_dict()
    output["judgment"] = {
        "conclusion": judgment.conclusion.value,
        "confidence": judgment.confidence,
        "decisive_evidence_ids": list(judgment.decisive_evidence_ids),
        "critical_gap": judgment.critical_gap,
        "first_action": judgment.first_action,
        "verification_condition": judgment.verification_condition,
        "stop_condition": judgment.stop_condition,
        "assumptions": list(judgment.assumptions),
    }
    output["validation_errors"] = list(errors)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())


