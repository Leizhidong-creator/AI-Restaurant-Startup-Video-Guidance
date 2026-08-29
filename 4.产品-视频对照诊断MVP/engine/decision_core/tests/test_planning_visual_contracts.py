from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import (
    CallableModelQuestionPlanner,
    CallableVisionAnalyzer,
    Conclusion,
    EvidenceKind,
    EvidenceRecord,
    Judgment,
    QuestionCandidate,
    SessionSnapshot,
    Stage,
    ToolName,
    ToolStatus,
    validate_judgment,
)


class PlanningVisualContractTest(unittest.TestCase):
    def test_model_planner_rejects_out_of_set_fact(self) -> None:
        planner = CallableModelQuestionPlanner(
            lambda prompt: {"fact_key": "invented", "question": "?", "rationale": "x"}
        )
        with self.assertRaises(ValueError):
            planner.select(
                SessionSnapshot(stage=Stage.SITE_SELECTION, facts={}),
                [QuestionCandidate("location", "地址？", "核验位置")],
            )

    def test_visual_observation_requires_frame_locator(self) -> None:
        analyzer = CallableVisionAnalyzer(
            lambda media, prompt: {
                "coverage_codes": ["front"],
                "observations": [{"observation": "门头被树遮挡"}],
                "inferences": [],
                "missing_captures": [],
            },
            model_name="fake-vision",
        )
        result = analyzer.analyze(
            ["private://video"],
            stage="site_selection",
            category="面馆",
            target_period="午餐",
        )
        self.assertEqual(result.status, ToolStatus.INVALID_RESULT)

    def test_visual_observation_and_inference_are_separate(self) -> None:
        analyzer = CallableVisionAnalyzer(
            lambda media, prompt: {
                "coverage_codes": ["front", "entrance"],
                "observations": [
                    {"observation": "店门朝向内街", "frame_locator": "00:12", "confidence": 0.9}
                ],
                "inferences": [
                    {
                        "inference": "自然曝光可能受限",
                        "supporting_frame_locators": ["00:12"],
                        "confidence": 0.7,
                    }
                ],
                "missing_captures": ["parking"],
            },
            model_name="fake-vision",
        )
        result = analyzer.analyze(
            ["private://video"],
            stage="site_selection",
            category="面馆",
            target_period="午餐",
        )
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertEqual(result.data["observations"][0]["frame_locator"], "00:12")
        self.assertEqual(result.data["missing_captures"], ["parking"])

    def test_visual_inference_requires_supporting_frame(self) -> None:
        analyzer = CallableVisionAnalyzer(
            lambda media, prompt: {
                "coverage_codes": ["front"],
                "observations": [
                    {"observation": "店门朝向内街", "frame_locator": "00:12"}
                ],
                "inferences": [{"inference": "曝光可能受限", "supporting_frame_locators": []}],
                "missing_captures": [],
            },
            model_name="fake-vision",
        )
        result = analyzer.analyze(
            ["private://video"],
            stage="site_selection",
            category="面馆",
            target_period="午餐",
        )
        self.assertEqual(result.status, ToolStatus.INVALID_RESULT)

    def test_judgment_rejects_unknown_evidence(self) -> None:
        snapshot = SessionSnapshot(
            stage=Stage.SITE_SELECTION,
            facts={},
            evidence={
                "visual:1": EvidenceRecord(
                    evidence_id="visual:1",
                    kind=EvidenceKind.OBSERVED,
                    source="video",
                    summary="门头朝内",
                )
            },
        )
        judgment = Judgment(
            conclusion=Conclusion.DO_NOT_PROCEED,
            confidence=0.8,
            decisive_evidence_ids=("invented:1",),
            counter_evidence_ids=(),
            critical_gap=None,
            first_action="暂停付款",
            verification_condition="补齐午餐动线",
            stop_condition="门口有效客流不足",
        )
        errors = validate_judgment(judgment, snapshot)
        self.assertIn("unknown evidence IDs: invented:1", errors)

    def test_judgment_must_follow_directive_allowlist(self) -> None:
        snapshot = SessionSnapshot(
            stage=Stage.SITE_SELECTION,
            facts={},
            evidence={
                "visual:1": EvidenceRecord(
                    evidence_id="visual:1",
                    kind=EvidenceKind.OBSERVED,
                    source="video",
                    summary="入口被遮挡",
                )
            },
        )
        judgment = Judgment(
            conclusion=Conclusion.PROCEED_WITH_CONDITIONS,
            confidence=0.6,
            decisive_evidence_ids=("visual:1",),
            counter_evidence_ids=(),
            critical_gap="午餐有效客流",
            first_action="补拍午餐入口",
            verification_condition="入口曝光达到预设门槛",
            stop_condition="无法形成可见入口",
        )
        errors = validate_judgment(
            judgment,
            snapshot,
            allowed_conclusions=(Conclusion.INSUFFICIENT_EVIDENCE,),
        )
        self.assertIn("conclusion not allowed by directive: proceed_with_conditions", errors)

    def test_inference_only_cannot_support_substantive_conclusion(self) -> None:
        snapshot = SessionSnapshot(
            stage=Stage.SITE_SELECTION,
            facts={},
            evidence={
                "inference:1": EvidenceRecord(
                    evidence_id="inference:1",
                    kind=EvidenceKind.INFERENCE,
                    source="model",
                    summary="曝光可能受限",
                )
            },
        )
        judgment = Judgment(
            conclusion=Conclusion.DO_NOT_PROCEED,
            confidence=0.7,
            decisive_evidence_ids=("inference:1",),
            counter_evidence_ids=("inference:1",),
            critical_gap=None,
            first_action="暂停付款",
            verification_condition="补充现场视频",
            stop_condition="验证后仍不可见",
        )
        errors = validate_judgment(judgment, snapshot)
        self.assertTrue(any("non-inference" in item for item in errors))
        self.assertTrue(any("both decisive and counterevidence" in item for item in errors))


if __name__ == "__main__":
    unittest.main()


