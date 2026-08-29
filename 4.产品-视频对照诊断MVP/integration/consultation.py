"""端到端核心 loop：一句话 + 预置案例视频 → 案例解构 → 个体迁移 → 三段式复盘(PRD §8.9)。

分工:AI(model_call)只做语义判断(解构/对照);这里把结果**确定性组装**成产品的三段式输出,
不再调模型、不引入新幻觉——符合"规则组装展示、AI 负责判断"的产品纪律。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from platform_knowledge import PlatformKnowledgeRetriever
from reasoning import CaseDecode, TransferAssessment, assess_transfer, decode_case
from restaurant_handoff import ToolStatus, calculate_business_metrics

LEARN_ORDER = ["可以直接学", "需要改造", "不建议复制", "待验证"]
_NEXT_PRIORITY = {"待验证": 0, "需要改造": 1, "可以直接学": 2, "不建议复制": 3}


@dataclass
class Consultation:
    why_success: list[str] = field(default_factory=list)              # 第一块
    can_learn: dict[str, list[dict]] = field(default_factory=dict)    # 第二块 verdict -> items
    next_steps: list[dict] = field(default_factory=list)             # 第三块
    evidence_ids: list[str] = field(default_factory=list)
    insufficient: bool = False
    metrics: dict | None = None                                      # 算账工具的确定性结果
    decode: CaseDecode | None = None
    transfer: TransferAssessment | None = None


def _compute_metrics(user_numbers: dict | None) -> tuple[str, str | None, dict | None]:
    """有数字就真调算账工具,返回(喂给 prompt 的说明, 证据 id, 结构化结果)。"""
    if not user_numbers:
        return "", None, None
    res = calculate_business_metrics(user_numbers)
    if res.status == ToolStatus.OK:
        d, eid = res.data, res.evidence_ids[0]
        note = (
            f"（工具确定性算出·CNY，证据 id {eid}）"
            f"保本需日营业额 {d['break_even_daily_revenue']}；"
            f"预估月利润(税前) {d['monthly_operating_profit_before_tax']}；"
            f"离保本日差口 {d['daily_revenue_gap_to_break_even']}（正=已过线，负=还没到）。"
        )
        if "cash_runway_months_at_current_model" in d:
            note += f" 现金跑道约 {d['cash_runway_months_at_current_model']} 个月。"
        return note, eid, d
    return f"（暂时算不了：{res.error_code}；需要用户补齐相关数字后再算。）", None, None


def run_consultation(
    video_understanding: str,
    user_situation: str,
    *,
    retriever: PlatformKnowledgeRetriever,
    model_call,
    user_numbers: dict | None = None,
    max_next: int = 3,
) -> Consultation:
    decode = decode_case(video_understanding, retriever=retriever, model_call=model_call)
    metrics_note, metrics_eid, metrics_data = _compute_metrics(user_numbers)
    transfer = assess_transfer(
        decode, user_situation, retriever=retriever, model_call=model_call,
        metrics_note=metrics_note, metrics_evidence_id=metrics_eid,
    )

    # 第一块:别人为什么成功 = 一句话 + 核心变量维度
    why = [decode.summary] if decode.summary else []
    why += [f"{d.name}：{d.why}" for d in decode.dimensions if d.role == "核心变量"]

    # 第二块:能学/别照搬 = 按四类分组
    can_learn: dict[str, list[dict]] = {v: [] for v in LEARN_ORDER}
    for it in transfer.items:
        can_learn.setdefault(it.verdict, []).append(
            {"point": it.point, "reason": it.reason, "evidence_ids": it.evidence_ids}
        )

    # 第三块:下一步 = 按优先级取 action(待验证>需改>可学),最多 max_next
    steps = [
        {"action": it.action, "point": it.point, "verdict": it.verdict, "evidence_ids": it.evidence_ids}
        for it in sorted(transfer.items, key=lambda x: _NEXT_PRIORITY.get(x.verdict, 9))
        if it.action
    ][:max_next]

    evidence = sorted(
        {e for it in transfer.items for e in it.evidence_ids}
        | {e for d in decode.dimensions for e in d.evidence_ids}
    )

    return Consultation(
        why_success=why,
        can_learn=can_learn,
        next_steps=steps,
        evidence_ids=evidence,
        insufficient=transfer.insufficient,
        metrics=metrics_data,
        decode=decode,
        transfer=transfer,
    )


def render(c: Consultation) -> str:
    """产品首屏可读版三段式(前端可直接用结构化字段,这里给文本演示)。"""
    out = ["【一、别人为什么成功】"]
    out += [f"  · {w}" for w in c.why_success] or ["  ·（暂无法从视频确认）"]
    out.append("\n【二、你能学什么、别照搬什么】")
    for v in LEARN_ORDER:
        items = c.can_learn.get(v) or []
        if not items:
            continue
        out.append(f"  ▸ {v}")
        out += [f"     - {it['point']}：{it['reason']}" for it in items]
    out.append("\n【三、下一步做什么】")
    out += [f"  {i}. {s['action']}" for i, s in enumerate(c.next_steps, 1)] or ["  1.（先补齐关键信息再定）"]
    if c.metrics:
        m = c.metrics
        out.append(
            f"\n【账（工具算的·CNY）】保本日营业额 {m['break_even_daily_revenue']}"
            f"｜预估月利润(税前) {m['monthly_operating_profit_before_tax']}"
            f"｜离保本日差口 {m['daily_revenue_gap_to_break_even']}"
        )
    if c.insufficient:
        out.append("\n有几点还需你确认（上面已标「待验证」）——不足的地方我不硬编。")
    return "\n".join(out)


