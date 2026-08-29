from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff.retrieval import load_documents


class KnowledgeDataTest(unittest.TestCase):
    def test_manifest_matches_valid_documents(self) -> None:
        manifest = json.loads((ROOT / "knowledge" / "manifest.json").read_text(encoding="utf-8"))
        documents = load_documents(ROOT / "knowledge" / "platform.jsonl")
        self.assertEqual(len(documents), manifest["document_count"])
        self.assertEqual(len({item.knowledge_id for item in documents}), len(documents))
        self.assertTrue(all(item.source_url for item in documents))
        self.assertTrue(all(item.review_status for item in documents))
        self.assertTrue(all(item.scope == "platform" for item in documents))
        self.assertTrue(all(item.evidence_grade in {"secondary", "reviewed", "golden"} for item in documents))
        self.assertTrue(all(item.limitations for item in documents))
        grade_counts = {
            grade: sum(item.evidence_grade == grade for item in documents)
            for grade in ("reviewed", "secondary", "golden")
        }
        self.assertEqual(grade_counts, manifest["counts_by_evidence_grade"])
        self.assertEqual(
            sum(item.knowledge_id.startswith("case-") for item in documents),
            manifest["case_count"],
        )
        self.assertEqual(
            sum(item.knowledge_id.startswith("method-") for item in documents),
            manifest["method_count"],
        )


if __name__ == "__main__":
    unittest.main()


