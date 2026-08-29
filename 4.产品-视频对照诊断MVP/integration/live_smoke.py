"""Live 冒烟:真调 DeepSeek + 真检索餐饮专家 KB,跑通 案例解构 → 个体迁移。
只打印结果,绝不打印 key。
运行: cd 4.产品-视频对照诊断MVP/integration && python3 live_smoke.py
"""

import sys
from pathlib import Path

_INTEGRATION = Path(__file__).resolve().parent
_DC = _INTEGRATION.parent / "engine" / "decision_core"
_KB = _DC / "knowledge" / "platform.jsonl"
for p in (str(_INTEGRATION), str(_DC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from platform_knowledge import PlatformKnowledgeRetriever  # noqa: E402
from reasoning import assess_transfer, decode_case  # noqa: E402
from deepseek_client import make_deepseek_model_call  # noqa: E402

# 模拟一条"用户刷到的成功案例视频"的理解(真实产品里由 Qwen Omni 产出)
VIDEO = (
    "一条抖音爆火视频:大学城正门口的网红奶茶店,天天排长队,主打一款高颜值招牌奶茶,"
    "学生举着拍照发朋友圈;店面不大、两三个人在忙,视频里说月流水很高。"
)
# 用户自己的情况(真实产品里由白话建档 + 选项/连麦获得)
USER = "我在一个新建社区的临街铺子,30平,想开奶茶店,预算8万,以前没开过店,周边多是居民和上班族,没有学校。"


def main() -> None:
    r = PlatformKnowledgeRetriever(documents_path=str(_KB))
    print(f"KB {r.mode}; 开始真调 DeepSeek…\n")
    call = make_deepseek_model_call()

    print("① 案例解构（decode_case，真模型 + 餐饮专家 KB）")
    d = decode_case(VIDEO, retriever=r, model_call=call)
    print("  一句话:", d.summary)
    for dim in d.dimensions:
        print(f"  · [{dim.name}|{dim.role}] {dim.why}  证据{dim.evidence_ids}")
    print("  待确认:", d.unverified)

    print("\n② 个体迁移（assess_transfer,对照用户情况）")
    a = assess_transfer(d, USER, retriever=r, model_call=call)
    print("  总结论:", a.overall, " | insufficient:", a.insufficient)
    for it in a.items:
        print(f"  · [{it.verdict}] {it.point}")
        print(f"      理由:{it.reason}")
        print(f"      行动:{it.action}")
        print(f"      边界:{it.boundary}  证据{it.evidence_ids}")


if __name__ == "__main__":
    main()


