"""服务端确定性辅助(assist):不指望实时语音模型自主调工具。

实测(PRD §23 2026-07-23):12 场真实会话模型自主 function call 为 0 次,
而服务端"后台通知"注入通道 100% 生效。故把工具纪律搬到服务端:
用户每句转写到达时,机械地识别"带标签的数字"触发确定性计算、
领域关键词触发平台知识检索,结果以后台通知文本注入对话。

边界(诚实原则):只解析"标签紧邻数字"的明确表述(如"租金1万2"),
不猜测无标签数字属于哪个字段——语义归属是模型的事,不用正则装智能。
"""

import re
from decimal import Decimal
from typing import Any

# 标签 → BusinessMetricsInput 字段。标签必须紧邻数字(中间容忍少量助词),
# 无标签数字一律忽略。
_METRIC_LABELS: list[tuple[str, str]] = [
    (r"租金|房租", "monthly_rent"),
    (r"人工|工资|人力成本", "monthly_labor_cost"),
    (r"水电|杂费|物业|其他固定", "monthly_other_fixed_cost"),
    (r"营业额|流水|月收入|月入", "monthly_revenue"),
]

# 数字(支持 1.2万 / 1万2 / 8000 / 8千):group1=数值 group2=单位 group3=万后紧邻尾数
_NUMBER = r"(\d+(?:\.\d+)?)\s*(万|千)?(\d)?"
# 标签与数字之间允许的填充(每月/大概/一个月/是/要 等)
_FILLER = r"[\s,，:：的是要每个月大概左右约得]{0,8}"

_COST_RATE_PATTERN = re.compile(
    r"(?:食材|原料)?成本(?:率|占比)" + _FILLER + r"(\d+(?:\.\d+)?)\s*%"
)

_KB_TRIGGER = re.compile(
    r"租|铺|店|加盟|成本|客|生意|外卖|菜单|定价|价|开业|亏|营业|装修|选址|人流|"
    r"流水|预算|回本|保本|利润|转让|品牌|奶茶|咖啡|餐"
)


def _parse_amount(value: str, unit: str | None, tail: str | None) -> Decimal:
    """把 (1.2, 万, None) / (1, 万, 2) / (8, 千, None) / (8000, None, None) 解析为元。"""
    base = Decimal(value)
    if unit == "万":
        amount = base * 10000
        if tail:  # 1万2 → 12000
            amount += Decimal(tail) * 1000
        return amount
    if unit == "千":
        return base * 1000
    return base


def extract_metric_updates(text: str) -> dict[str, Any]:
    """从转写文本里提取"标签紧邻数字"的经营指标,返回 BusinessMetricsInput 参数。"""
    updates: dict[str, Any] = {}
    for label_pattern, field in _METRIC_LABELS:
        m = re.search(r"(?:" + label_pattern + r")" + _FILLER + _NUMBER, text)
        if m and m.group(1):
            amount = _parse_amount(m.group(1), m.group(2), m.group(3))
            if amount > 0:
                updates[field] = str(amount)
    rate_match = _COST_RATE_PATTERN.search(text)
    if rate_match:
        rate = Decimal(rate_match.group(1)) / 100
        if Decimal("0") < rate < Decimal("1"):
            updates["ingredient_cost_rate"] = str(rate)
    return updates


def should_query_kb(text: str) -> bool:
    """领域关键词门:闲聊("有看到我的画面吗")不去打扰知识库。"""
    return len(text) >= 6 and bool(_KB_TRIGGER.search(text))


_FIELD_CN = {
    "monthly_rent": "月租金",
    "monthly_labor_cost": "月人工",
    "monthly_other_fixed_cost": "月其他固定成本",
    "monthly_revenue": "月营业额",
    "ingredient_cost_rate": "食材成本率",
}


def compose_assist_message(
    updates: dict[str, Any],
    metrics: dict[str, Any] | None,
    kb: dict[str, Any] | None,
) -> str:
    """把确定性计算结果与知识命中拼成一条后台通知。无实质内容时返回空串。"""
    parts: list[str] = []
    if metrics is not None and updates:
        used = "、".join(
            f"{_FIELD_CN.get(k, k)}={v}" for k, v in updates.items()
        )
        if metrics.get("available"):
            fields = []
            if metrics.get("break_even_monthly_revenue") is not None:
                fields.append(f"保本月营业额≈{metrics['break_even_monthly_revenue']}元")
            if metrics.get("break_even_daily_revenue") is not None:
                fields.append(f"保本日营业额≈{metrics['break_even_daily_revenue']}元")
            if metrics.get("monthly_operating_profit") is not None:
                fields.append(f"月经营利润≈{metrics['monthly_operating_profit']}元")
            if metrics.get("safety_margin_rate") is not None:
                fields.append(f"安全边际≈{metrics['safety_margin_rate']}")
            missing = metrics.get("missing_fields") or []
            result = ";".join(fields) if fields else "计算已完成"
            parts.append(
                f"后台已按用户刚说的数({used})做了确定性计算:{result}。"
                "请用大白话转述,并说明是按 TA 刚给的数算的;不要自己心算改数。"
                + (
                    f"若要算得更全,只差:{'、'.join(_FIELD_CN.get(f, f) for f in missing)}"
                    f"——最多追问其中一个。"
                    if missing
                    else ""
                )
            )
        else:
            missing = metrics.get("missing_fields") or []
            need = "、".join(_FIELD_CN.get(f, f) for f in missing[:4])
            parts.append(
                f"用户刚提到了数字({used}),后台试算保本线还缺:{need}。"
                "本轮最多向用户追问其中一个最关键的数,不要一次全问。"
            )
    if kb is not None:
        hits = (kb.get("data") or {}).get("hits") or []
        lines = []
        for hit in hits[:2]:
            content = str(hit.get("content") or "").strip().replace("\n", " ")
            if content:
                lines.append(f"[{hit.get('id')}] {content[:120]}")
        if lines:
            parts.append(
                "平台知识库与当前话题相关的判断依据:" + " / ".join(lines) + "。"
                "如引用,请转成大白话,结论处可提到这是行业经验。"
            )
    if not parts:
        return ""
    return "【后台通知】" + "".join(parts)


