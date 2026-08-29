"""端到端核心 loop 测试(离线:真检索器 + 假 model_call)。"""

import json
import sys
import unittest
from pathlib import Path

_INTEGRATION = Path(__file__).resolve().parents[1]
_DC = _INTEGRATION.parent / "engine" / "decision_core"
_KB = _DC / "knowledge" / "platform.jsonl"
for p in (str(_INTEGRATION), str(_DC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from consultation import run_consultation, render, LEARN_ORDER  # noqa: E402
from platform_knowledge import PlatformKnowledgeRetriever  # noqa: E402


def _fake_model(prompt: str) -> str:
    # 按 prompt 分辨:解构 vs 对照
    if "可以直接学" in prompt:  # 迁移
        return json.dumps({
            "overall": "能学一半",
            "items": [
                {"verdict": "可以直接学", "point": "招牌单品做传播", "reason": "轻投入不冲突",
                 "evidence_ids": ["rag:platform:a:2.0"], "action": "定一款记忆点单品试两周", "boundary": "看能否做出记忆点"},
                {"verdict": "不建议复制", "point": "排队打卡", "reason": "社区无学生客流",
                 "evidence_ids": [], "action": "明晚数会进店消费的人", "boundary": "实测客流足则重估"},
                {"verdict": "待验证", "point": "盈利真实性", "reason": "证据不足",
                 "evidence_ids": [], "action": "算保本点、对比周边客流", "boundary": "日需50杯而客流不足则不做"},
            ],
            "insufficient": True,
        }, ensure_ascii=False)
    return json.dumps({  # 解构
        "summary": "靠大学城客流+高颜值招牌",
        "dimensions": [
            {"name": "选址", "facts": ["大学城核心"], "why": "学生密集", "role": "核心变量",
             "preconditions": ["大学城客流"], "evidence_ids": ["rag:platform:b:2.0"]},
            {"name": "运营", "facts": ["短视频引流"], "why": "热度放大", "role": "无法验证",
             "preconditions": [], "evidence_ids": []},
        ],
        "unverified": ["真实营收未知"],
    }, ensure_ascii=False)


class ConsultationTests(unittest.TestCase):
    def setUp(self):
        self.r = PlatformKnowledgeRetriever(documents_path=str(_KB))

    def test_three_blocks_assemble(self):
        c = run_consultation("大学城奶茶店", "社区铺子想开奶茶,预算8万,新手",
                             retriever=self.r, model_call=_fake_model)
        # 第一块:含一句话 + 核心变量维度(选址),不含"无法验证"维度
        self.assertTrue(c.why_success)
        self.assertTrue(any("选址" in w for w in c.why_success))
        self.assertFalse(any("运营" in w for w in c.why_success))
        # 第二块:三类都在
        self.assertTrue(c.can_learn["可以直接学"])
        self.assertTrue(c.can_learn["不建议复制"])
        self.assertTrue(c.can_learn["待验证"])
        # 第三块:待验证优先排在最前
        self.assertEqual(c.next_steps[0]["verdict"], "待验证")
        # 编造的假 id 被剥掉(a/b 都不在真实 KB 里)、insufficient 传递
        self.assertNotIn("rag:platform:a:2.0", c.evidence_ids)
        self.assertTrue(c.insufficient)

    def test_metrics_computed_when_numbers_given(self):
        nums = {"expected_daily_revenue": 400, "operating_days_per_month": 30,
                "contribution_margin_rate": 0.6, "monthly_rent": 4000,
                "monthly_labor_cost": 3000, "monthly_other_fixed_cost": 1500}
        c = run_consultation("大学城奶茶店", "社区想开奶茶,预算8万",
                             retriever=self.r, model_call=_fake_model, user_numbers=nums)
        self.assertIsNotNone(c.metrics)
        self.assertGreater(c.metrics["break_even_daily_revenue"], 0)  # 保本日营业额算出来了
        self.assertIn("保本日营业额", render(c))  # 账也出现在复盘里

    def test_no_numbers_no_metrics(self):
        c = run_consultation("x", "y", retriever=self.r, model_call=_fake_model)
        self.assertIsNone(c.metrics)

    def test_render_has_three_headers(self):
        c = run_consultation("x", "y", retriever=self.r, model_call=_fake_model)
        text = render(c)
        for h in ("别人为什么成功", "你能学什么", "下一步做什么"):
            self.assertIn(h, text)


if __name__ == "__main__":
    unittest.main()


