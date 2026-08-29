"""Live 端到端演示:一句话 + 预置案例 → 真调 DeepSeek + 餐饮专家 KB → 三段式复盘(产品首屏)。
运行: cd 4.产品-视频对照诊断MVP/integration && python3 demo_consultation.py
只打印结果,不打印 key。
"""

import sys
from pathlib import Path

_INTEGRATION = Path(__file__).resolve().parent
_DC = _INTEGRATION.parent / "engine" / "decision_core"
_KB = _DC / "knowledge" / "platform.jsonl"
for p in (str(_INTEGRATION), str(_DC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from consultation import run_consultation, render  # noqa: E402
from deepseek_client import make_deepseek_model_call  # noqa: E402
from platform_knowledge import PlatformKnowledgeRetriever  # noqa: E402

VIDEO = (
    "抖音爆火视频:大学城正门口网红奶茶店,天天排长队,主打一款高颜值招牌奶茶,"
    "学生举着拍照发朋友圈,店面不大两三人在忙,口播说月流水很高。"
)
USER = "我在新建社区的临街铺子,30平,想开奶茶店,预算8万,没开过店,周边多是居民和上班族,没有学校。"
# 用户给的数字(建档/选项收集来)——有了就真算账
USER_NUMBERS = {
    "expected_daily_revenue": 400,        # 预估日营业额
    "operating_days_per_month": 30,
    "contribution_margin_rate": 0.6,      # 毛利率
    "monthly_rent": 4000,
    "monthly_labor_cost": 3000,
    "monthly_other_fixed_cost": 1500,
}


def main() -> None:
    r = PlatformKnowledgeRetriever(documents_path=str(_KB))
    call = make_deepseek_model_call()
    print("真调 DeepSeek + 餐饮专家 KB + 算账工具 跑端到端…\n")
    c = run_consultation(VIDEO, USER, retriever=r, model_call=call, user_numbers=USER_NUMBERS)
    print(render(c))
    print(f"\n[引用餐饮专家证据 {len(c.evidence_ids)} 条: {', '.join(c.evidence_ids) or '无'}]")


if __name__ == "__main__":
    main()


