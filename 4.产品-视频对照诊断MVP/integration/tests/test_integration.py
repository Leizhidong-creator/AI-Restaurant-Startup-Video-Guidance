"""AI 集成桥接测试(离线,无需 embedding/网络/后端)。

运行:
  cd 4.产品-视频对照诊断MVP/integration
  python3 -m unittest tests.test_integration -v
"""

import sys
import unittest
from pathlib import Path

_INTEGRATION = Path(__file__).resolve().parents[1]          # integration/
_PRODUCT = _INTEGRATION.parent                              # 4.产品-...MVP/
_DC = _PRODUCT / "engine" / "decision_core"                 # 决策内核(restaurant_handoff)
_PLATFORM_JSONL = _DC / "knowledge" / "platform.jsonl"
for p in (str(_INTEGRATION), str(_DC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from platform_knowledge import KnowledgeHit, PlatformKnowledgeRetriever  # noqa: E402

# 注:实时会话指令的 SkillEngine 已由其他贡献者后端 DecisionCoreSkillEngineAdapter 承担
# (4.产品-视频对照诊断MVP/backend/src/yongge_online/integrations/decision_core.py),
# 本地 skill_engine.py 已退役。离线只保留平台 KB 检索器测试。


class PlatformKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.retriever = PlatformKnowledgeRetriever(documents_path=str(_PLATFORM_JSONL))

    def test_offline_mode(self):
        self.assertEqual(self.retriever.mode, "lexical_fallback")

    def test_search_returns_knowledge_hits(self):
        hits = self.retriever.search("大学城 人流 选址", limit=3)
        self.assertTrue(hits, "应能检索到相关平台知识")
        self.assertLessEqual(len(hits), 3)
        for hit in hits:
            self.assertIsInstance(hit, KnowledgeHit)
            self.assertTrue(hit.id.startswith("rag:platform:"))   # 稳定证据 id
            self.assertGreater(hit.score, 0)
            self.assertIn(hit.kind, {"golden", "reviewed", "secondary"})
            self.assertTrue(hit.content)

    def test_evidence_id_is_stable(self):
        a = self.retriever.search("人流 客流", limit=1)[0].id
        b = self.retriever.search("人流 客流", limit=1)[0].id
        self.assertEqual(a, b)

    def test_empty_query_returns_empty(self):
        self.assertEqual(self.retriever.search("   ", limit=3), [])

    def test_ranked_by_score_desc(self):
        hits = self.retriever.search("加盟 直营店 风险", limit=5)
        scores = [h.score for h in hits]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()


