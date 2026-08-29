"""案例解构(PRD §8.3)+ 个体迁移(PRD §8.8)—— AI 大脑的两段核心逻辑。

- 解构:把"看起来很火"拆成 选址/产品/客群/运营 四维,先事实后因果,区分核心变量/表面现象,标"待确认",每条挂餐饮专家 KB 证据 id。
- 迁移:拿用户情况 + 现场观察 和案例对照,给 可学 / 需改 / 不可复制 / 待验证 四类判断,每条五段(结论/理由/证据/行动/边界)。

设计:语义判断由注入的 model_call(prompt)->str(返回 JSON)完成;确定性数字走决策内核的
calculate_business_metrics;证据来自平台 KB(PlatformKnowledgeRetriever)。可用假 model_call 离线测结构。
纪律:不编数字、覆盖不到就 insufficient、结论不承诺赚钱——写进 prompt,也在解析层做基本校验。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from platform_knowledge import KnowledgeHit, PlatformKnowledgeRetriever

# ── 案例解构 ──────────────────────────────────────────────

CASE_DECODE_PROMPT = """你是餐饮专家，正在把一条"看起来很火"的门店视频拆给普通用户听。
只依据下面的视频理解和餐饮专家知识库，不要编造数字或事实。

视频理解：
{video}

可参考的餐饮专家知识库（每条带证据 id，可在 evidence_ids 里引用）：
{kb}

请从四个维度拆解，先说视频里能看到的事实，再解释可能的因果：选址、产品、客群、运营。
规则：
- 区分「核心成功变量 / 辅助因素 / 表面现象 / 无法验证」。
- 说明成功成立的前置条件（如大学城客流、特定供应链、主播影响力）。
- 不用"流量密码""品牌势能"等空泛词，要具体。
- 只看视频推不出真实营收/复购的，放进 unverified，不当结论。
- 拿不准的用"可能/大概率"留余地，别把推断说成事实。
- evidence_ids 只能填上面 KB 列表里真实出现的 id，**绝不编造 id/案例/数字/来源**；无对应支撑就留空（留空没关系，别硬凑）。

只输出 JSON：
{{"summary":"一句话它可能靠什么火",
  "dimensions":[{{"name":"选址","facts":["可观察事实"],"why":"可能的因果","role":"核心变量|辅助因素|表面现象|无法验证","preconditions":["前置条件"],"evidence_ids":["kb证据id"]}}],
  "unverified":["只看视频无法确认、需进一步验证的点"]}}"""


@dataclass
class DimensionDecode:
    name: str
    facts: list[str] = field(default_factory=list)
    why: str = ""
    role: str = ""
    preconditions: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)


@dataclass
class CaseDecode:
    summary: str
    dimensions: list[DimensionDecode] = field(default_factory=list)
    unverified: list[str] = field(default_factory=list)


def _only(cls, d: dict) -> dict:
    """只保留 cls 的 dataclass 字段,容忍真实模型多返回的字段。"""
    return {k: v for k, v in d.items() if k in cls.__dataclass_fields__}


def _render_kb(hits: list[KnowledgeHit]) -> str:
    if not hits:
        return "（本次没检索到相关知识；解构时如缺依据，请在 unverified 里说明）"
    return "\n".join(f"- [{h.id}]（{h.kind}）{h.content}" for h in hits)


def decode_case(
    video_understanding: str,
    *,
    retriever: PlatformKnowledgeRetriever,
    model_call,
    kb_limit: int = 5,
) -> CaseDecode:
    """拆解一条案例视频。model_call(prompt)->str 需返回上面约定的 JSON。"""
    hits = retriever.search(video_understanding, limit=kb_limit)
    valid = {h.id for h in hits}
    prompt = CASE_DECODE_PROMPT.format(video=video_understanding, kb=_render_kb(hits))
    data = json.loads(model_call(prompt))
    dims = [DimensionDecode(**_only(DimensionDecode, d)) for d in data.get("dimensions", [])]
    for dim in dims:
        dim.evidence_ids = [e for e in dim.evidence_ids if e in valid]  # 去掉编造的 id,不降级判断
    return CaseDecode(
        summary=data.get("summary", ""),
        dimensions=dims,
        unverified=list(data.get("unverified", [])),
    )


# ── 个体迁移 ──────────────────────────────────────────────

TRANSFER_PROMPT = """你是餐饮专家，把刚才拆解的成功案例和"用户自己的情况+现场观察"对照，判断哪些能学、哪些不能。
只依据给定信息和餐饮专家知识库，不要编造。

案例解构结论：
{case}

用户的情况与现场观察：
{user}

可参考的餐饮专家知识库（带证据 id）：
{kb}

算账（确定性工具结果，若有；涉及钱就直接用它、并可引用其证据 id）：
{metrics}

请给出对照判断，每条属于四类之一：可以直接学 / 需要改造 / 不建议复制 / 待验证。
每条必须五段齐全：结论、理由（为什么适用于这个用户）、证据（引用 kb 证据 id 或现场观察）、行动（用户下一步具体做什么，要有对象/地点/数量/时间）、边界（不确定性或会改变结论的条件）。
规则：
- 涉及保本/盈亏等数字，**直接用上面「算账」里的结果下判断、并引用其证据 id，自己绝不心算**；若「算账」显示缺数字或为空，就在 action 里让用户补齐这些数字再算。
- 有贴合的 KB 条目就在 evidence_ids 引用其真实 id、把话说肯定；**只有通用规律、没具体案例时，照样大胆给判断，但用"大概率/通常/我倾向于"这类留余地的说法**（evidence_ids 可留空，不要因此就降级为"待验证"）。
- "待验证"只留给**真的缺关键事实、或完全超出餐饮经验**的情况，不是"没引到案例"就用。
- evidence_ids 只能填上面 KB 列表里真实出现的 id，**绝不编造案例、数字、来源或 id**。
- 只有确实缺关键事实、给不出有用判断时才把 insufficient 置 true；能给出带余地的判断就不算 insufficient。
- 不承诺赚钱或开店成功。

只输出 JSON：
{{"overall":"一句话总结论",
  "items":[{{"verdict":"可以直接学|需要改造|不建议复制|待验证","point":"针对哪件事","reason":"...","evidence_ids":["..."],"action":"...","boundary":"..."}}],
  "insufficient":false}}"""


@dataclass
class TransferItem:
    verdict: str
    point: str = ""
    reason: str = ""
    evidence_ids: list[str] = field(default_factory=list)
    action: str = ""
    boundary: str = ""


@dataclass
class TransferAssessment:
    overall: str
    items: list[TransferItem] = field(default_factory=list)
    insufficient: bool = False


VALID_VERDICTS = {"可以直接学", "需要改造", "不建议复制", "待验证"}


def assess_transfer(
    case: CaseDecode,
    user_situation: str,
    *,
    retriever: PlatformKnowledgeRetriever,
    model_call,
    kb_limit: int = 5,
    metrics_note: str = "",
    metrics_evidence_id: str | None = None,
) -> TransferAssessment:
    """把案例解构和用户情况对照,给个体迁移判断。metrics_note 为算账工具的确定性结果(可选)。"""
    hits = retriever.search(f"{case.summary} {user_situation}", limit=kb_limit)
    valid = {h.id for h in hits}
    if metrics_evidence_id:
        valid.add(metrics_evidence_id)  # 允许引用算账证据 id
    case_text = json.dumps(
        {"summary": case.summary, "dimensions": [d.__dict__ for d in case.dimensions],
         "unverified": case.unverified},
        ensure_ascii=False,
    )
    prompt = TRANSFER_PROMPT.format(
        case=case_text, user=user_situation, kb=_render_kb(hits),
        metrics=metrics_note or "（用户暂未提供足够数字，无法算账；如判断需要，在 action 里让用户补齐再算）",
    )
    data = json.loads(model_call(prompt))
    items = [TransferItem(**_only(TransferItem, it)) for it in data.get("items", [])]
    for it in items:
        if it.verdict not in VALID_VERDICTS:
            raise ValueError(f"非法判断类别：{it.verdict}（必须是四类之一）")
        it.evidence_ids = [e for e in it.evidence_ids if e in valid]  # 去掉编造的 id,不降级判断
    return TransferAssessment(
        overall=data.get("overall", ""),
        items=items,
        insufficient=bool(data.get("insufficient", False)),
    )


