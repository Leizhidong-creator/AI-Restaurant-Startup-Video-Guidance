"""KB 覆盖 eval —— 离线测"当前 KB 够不够"。

测什么:给一组代表性问题(强区 + 薄弱区),用平台 KB 检索器看能否检索到**贴合的餐饮专家规则/案例**。
- 能检到高相关命中 → agent 有真实依据可用,答案会明显强过"拿视频问通用大模型"。
- 检不到 / 只有弱命中 → 该触发"证据不足"诚实 fallback = 覆盖缺口。

不测什么:最终答案文字质量(需实时模型 + 人评)。这里测的是**依据的有无与贴合度**,这正是"够不够"的核心。
局限:当前用离线词法检索(中文二元重叠),召回偏保守;生成向量索引后覆盖会更高。分数是方向性参考。

运行:
  cd 4.产品-视频对照诊断MVP/integration
  python3 eval_coverage.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_INTEGRATION = Path(__file__).resolve().parent
_DC = _INTEGRATION.parent / "engine" / "decision_core"
_PLATFORM_JSONL = _DC / "knowledge" / "platform.jsonl"
for p in (str(_INTEGRATION), str(_DC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from platform_knowledge import PlatformKnowledgeRetriever  # noqa: E402

# 代表性问题集:strong=KB 强区(开店前决策/选址/加盟/止损),weak=已知薄弱区(在营运营/增长)
QUESTIONS = [
    ("strong", "大学城旁边开一家奶茶店行不行，人流那么大"),
    ("strong", "加盟费八万的奶茶品牌值不值得加，会不会是坑"),
    ("strong", "这个铺子转让费要十九万，月租六千，该不该接"),
    ("strong", "两个店都在亏，要不要再开第三家摊平成本"),
    ("strong", "学校门口开小吃店能赚钱吗，学生有几千人"),
    ("strong", "店开在商场拐角，看着人来人往却没什么生意，为什么"),
    ("strong", "想在老乡鸡旁边开个木桶饭分它的客流，可行吗"),
    ("strong", "已经在营的小吃店，怎么把营业额做上去"),
    ("weak", "怎么做抖音短视频和直播给我的餐厅引流涨粉"),
    ("weak", "店员流动性太大，怎么管理和激励团队"),
    ("weak", "怎么设计会员体系和私域，让老顾客反复来"),
    ("weak", "怎么优化供应链、把食材采购成本降下来"),
]

GROUNDED = 0.15   # 词法 top1 分数高于此视为"有贴合依据"
THIN = 0.06       # 之间视为"弱依据"


def classify(top_score: float) -> str:
    if top_score >= GROUNDED:
        return "✅ 有依据"
    if top_score >= THIN:
        return "🟡 弱依据"
    return "❌ 无依据(该 fallback)"


def main() -> None:
    r = PlatformKnowledgeRetriever(documents_path=str(_PLATFORM_JSONL))
    print(f"KB 检索模式: {r.mode}（离线词法；向量索引会更高召回）\n")
    tally = {"strong": [], "weak": []}
    for zone, q in QUESTIONS:
        hits = r.search(q, limit=3)
        top = hits[0].score if hits else 0.0
        label = classify(top)
        tally[zone].append(label.split()[0])
        zone_cn = "强区" if zone == "strong" else "薄弱区"
        print(f"[{zone_cn}] {q}")
        print(f"   判定: {label}（top 分 {top:.2f}）")
        for h in hits:
            print(f"     - {h.score:.2f} [{h.kind}] {h.content[:38]}… ({h.id})")
        if not hits:
            print("     -（无命中）")
        print()

    def summ(labels):
        from collections import Counter
        c = Counter(labels)
        return f"有依据 {c.get('✅',0)} / 弱 {c.get('🟡',0)} / 无 {c.get('❌',0)}"

    print("=" * 56)
    print("小结")
    print(f"  强区(开店前决策/选址/加盟/止损): {summ(tally['strong'])}  —— 应尽量'有依据'")
    print(f"  薄弱区(在营运营/线上/团队/供应链): {summ(tally['weak'])}  —— '无依据'即诚实 fallback,是已知缺口")
    print("\n读法: 强区大面积'有依据' = 在核心用例上已强过 baseline;")
    print("      薄弱区大面积'无依据' = 那些域要扩视频才补得上(不是靠加选址类视频)。")


if __name__ == "__main__":
    main()


