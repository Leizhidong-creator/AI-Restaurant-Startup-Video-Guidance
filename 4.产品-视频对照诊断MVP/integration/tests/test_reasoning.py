"""案例解构 + 个体迁移 逻辑测试(离线:真检索器 + 假 model_call)。

运行:
  cd 4.产品-视频对照诊断MVP/integration
  python3 -m unittest tests.test_reasoning -v
"""

import json
import sys
import unittest
from pathlib import Path

_INTEGRATION = Path(__file__).resolve().parents[1]
_DC = _INTEGRATION.parent / "engine" / "decision_core"
_PLATFORM_JSONL = _DC / "knowledge" / "platform.jsonl"
for p in (str(_INTEGRATION), str(_DC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from platform_knowledge import PlatformKnowledgeRetriever  # noqa: E402
import reasoning  # noqa: E402
from reasoning import assess_transfer, decode_case  # noqa: E402


def _fake_decode_model(_prompt: str) -> str:
    return json.dumps({
        "summary": "靠大学城人流 + 高颜值招牌 + 内容传播",
        "dimensions": [
            {"name": "选址", "facts": ["开在大学城核心"], "why": "学生天然密集",
             "role": "核心变量", "preconditions": ["大学城客流"], "evidence_ids": ["rag:platform:x:2.0"]},
            {"name": "运营", "facts": ["靠短视频引流"], "why": "热度被放大",
             "role": "无法验证", "preconditions": [], "evidence_ids": []},
        ],
        "unverified": ["真实营收未知", "是否靠一次性主播流量未知"],
    }, ensure_ascii=False)


def _fake_transfer_model(_prompt: str) -> str:
    return json.dumps({
        "overall": "能学一半:招牌+传播可学,大学城客流学不了",
        "items": [
            {"verdict": "可以直接学", "point": "招牌单品做传播", "reason": "轻投入、和你品类不冲突",
             "evidence_ids": ["rag:platform:x:2.0"], "action": "先定一款记忆点单品试两周", "boundary": "看你能不能做出记忆点"},
            {"verdict": "不建议复制", "point": "复制排队打卡", "reason": "你的社区没有大学城客流",
             "evidence_ids": [], "action": "明晚数会进店消费的人", "boundary": "若实测客流足则重估"},
        ],
        "insufficient": False,
    }, ensure_ascii=False)


class ReasoningTests(unittest.TestCase):
    def setUp(self):
        self.retriever = PlatformKnowledgeRetriever(documents_path=str(_PLATFORM_JSONL))

    def test_decode_uses_kb_and_returns_structure(self):
        decode = decode_case("大学城奶茶店,排长队,高颜值招牌", retriever=self.retriever, model_call=_fake_decode_model)
        self.assertTrue(decode.summary)
        self.assertEqual(len(decode.dimensions), 2)
        self.assertEqual(decode.dimensions[0].role, "核心变量")
        self.assertTrue(decode.unverified)  # 待确认项保留

    def test_transfer_returns_five_part_items(self):
        decode = decode_case("大学城奶茶店", retriever=self.retriever, model_call=_fake_decode_model)
        result = assess_transfer(decode, "社区铺子,想开奶茶,预算8万,新手",
                                 retriever=self.retriever, model_call=_fake_transfer_model)
        self.assertTrue(result.overall)
        self.assertEqual(len(result.items), 2)
        for it in result.items:
            self.assertIn(it.verdict, reasoning.VALID_VERDICTS)
            self.assertTrue(it.reason and it.action and it.boundary)  # 五段齐全

    def test_fabricated_evidence_stripped(self):
        # 模型引用一个 KB 里不存在的 id → 应被悄悄剥掉(不降级、不报错)
        fake = lambda _p: json.dumps({"overall": "x", "items": [
            {"verdict": "需要改造", "point": "p", "reason": "r", "action": "a", "boundary": "b",
             "evidence_ids": ["rag:platform:__fake__:9.9"]}], "insufficient": False})
        decode = decode_case("x", retriever=self.retriever, model_call=_fake_decode_model)
        res = assess_transfer(decode, "y", retriever=self.retriever, model_call=fake)
        self.assertEqual(res.items[0].verdict, "需要改造")           # 判断保留
        self.assertNotIn("rag:platform:__fake__:9.9", res.items[0].evidence_ids)  # 假证据剥掉

    def test_invalid_verdict_rejected(self):
        bad = lambda _p: json.dumps({"overall": "x", "items": [{"verdict": "随便学学"}], "insufficient": False})
        decode = decode_case("x", retriever=self.retriever, model_call=_fake_decode_model)
        with self.assertRaises(ValueError):
            assess_transfer(decode, "y", retriever=self.retriever, model_call=bad)

    def test_prompts_encode_discipline(self):
        self.assertIn("unverified", reasoning.CASE_DECODE_PROMPT)
        self.assertIn("不用", reasoning.CASE_DECODE_PROMPT)  # 不用空泛词
        for token in ("大概率", "绝不编造", "五段", "不承诺"):
            self.assertIn(token, reasoning.TRANSFER_PROMPT)


if __name__ == "__main__":
    unittest.main()


