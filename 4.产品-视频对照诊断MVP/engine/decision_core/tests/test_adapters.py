from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import (
    CallableEvidenceTool,
    SearchHit,
    ToolStatus,
    retrieval_hits_to_result,
)


class EvidenceAdapterTest(unittest.TestCase):
    def test_zero_is_a_valid_required_argument(self) -> None:
        tool = CallableEvidenceTool(
            lambda arguments: {
                "status": "ok",
                "evidence_ids": ["tool:zero:1"],
                "data": {"value": arguments["value"]},
            },
            source="test:v1",
            required_arguments=("value",),
        )
        self.assertEqual(tool.run({"value": 0}).status, ToolStatus.OK)

    def test_blank_required_argument_is_invalid_input(self) -> None:
        tool = CallableEvidenceTool(
            lambda arguments: {},
            source="test:v1",
            required_arguments=("location",),
        )
        result = tool.run({"location": "  "})
        self.assertEqual(result.status, ToolStatus.INVALID_INPUT)

    def test_non_mapping_response_is_invalid_result(self) -> None:
        tool = CallableEvidenceTool(lambda arguments: None, source="test:v1")
        result = tool.run({})
        self.assertEqual(result.status, ToolStatus.INVALID_RESULT)
        self.assertEqual(result.error_code, "tool_response_must_be_mapping")

    def test_ok_without_evidence_is_invalid_result(self) -> None:
        tool = CallableEvidenceTool(
            lambda arguments: {"status": "ok", "data": {"value": 1}},
            source="test:v1",
        )
        self.assertEqual(tool.run({}).status, ToolStatus.INVALID_RESULT)

    def test_transport_error_is_unavailable(self) -> None:
        def fail(arguments):
            raise TimeoutError("timeout")

        tool = CallableEvidenceTool(fail, source="test:v1")
        result = tool.run({})
        self.assertEqual(result.status, ToolStatus.UNAVAILABLE)
        self.assertEqual(result.error_code, "TimeoutError")

    def test_retrieval_hits_keep_stable_evidence_ids(self) -> None:
        hit = SearchHit(
            evidence_id="rag:platform:case-1:1.0",
            knowledge_id="case-1",
            title="案例",
            snippet="摘要",
            score=0.8,
            source_url="https://example.com",
            source_locator="00:10-00:20",
            published_at=None,
            review_status="checked",
            evidence_grade="golden",
            retrieval_mode="dense_vector",
        )
        result = retrieval_hits_to_result([hit], source="rag:test")
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertEqual(result.evidence_ids, ("rag:platform:case-1:1.0",))

    def test_empty_retrieval_is_no_hit_not_unavailable(self) -> None:
        result = retrieval_hits_to_result([], source="rag:test")
        self.assertEqual(result.status, ToolStatus.NO_HIT)


if __name__ == "__main__":
    unittest.main()


