from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .contracts import (
    Conclusion,
    NextAction,
    QuestionCandidate,
    SessionSnapshot,
    SkillDirective,
    Stage,
    ToolName,
    ToolResult,
    ToolStatus,
)
from .planning import QuestionPlanner
from .visual import capture_checklist


@dataclass(frozen=True)
class FactSpec:
    key: str
    question: str
    decision_impact: str
    evidence_request: str | None = None

    def candidate(self) -> QuestionCandidate:
        return QuestionCandidate(
            fact_key=self.key,
            question=self.question,
            decision_impact=self.decision_impact,
            evidence_request=self.evidence_request,
        )


FACT_SPECS: dict[str, FactSpec] = {
    "payment_or_signature_within_72h": FactSpec(
        "payment_or_signature_within_72h",
        "未来 72 小时内是否必须付款、交定金或签字？",
        "决定是否先暂停不可逆承诺。",
        "付款通知、合同节点或聊天记录",
    ),
    "deposit_paid": FactSpec(
        "deposit_paid",
        "定金或不可退费用是否已经支付？金额多少？",
        "决定止损空间和证据保全优先级。",
        "付款凭证",
    ),
    "funding_type": FactSpec(
        "funding_type",
        "投入资金属于自有、借款还是抵押所得？",
        "高杠杆会缩短验证窗口。",
        "仅需说明资金性质，暂勿上传敏感账户信息",
    ),
    "borrowed_amount": FactSpec(
        "borrowed_amount",
        "本项目关联借款本金还有多少？",
        "决定现金流与家庭风险边界。",
    ),
    "maximum_affordable_loss": FactSpec(
        "maximum_affordable_loss",
        "在不影响家庭基本生活的前提下，最多能承受损失多少？",
        "约束项目的停止条件。",
    ),
    "location": FactSpec(
        "location",
        "请提供门店准确定位或可核验地址。",
        "用于核验动线、竞品和位置条件。",
        "地图定位；公开演示时可脱敏到道路或商圈",
    ),
    "scene_type": FactSpec(
        "scene_type",
        "铺位属于外街、内街、商场、社区、学校、写字楼还是场馆？",
        "不同场景的有效客流形成机制不同。",
    ),
    "category": FactSpec(
        "category",
        "门店具体卖什么，核心消费时段是什么？",
        "品类决定目标客群、毛利和动线要求。",
    ),
    "target_period": FactSpec(
        "target_period",
        "主要营业时段和准备拍摄/蹲点的目标时段是什么？",
        "现场证据必须对应真实消费时段。",
    ),
    "monthly_rent": FactSpec(
        "monthly_rent",
        "月租与物业合计多少元？",
        "构成固定成本和选址风险。",
        "合同或账单",
    ),
    "transfer_fee": FactSpec(
        "transfer_fee",
        "转让费及其他不可回收进场费用分别多少？",
        "决定不可逆投入规模。",
    ),
    "store_area_sqm": FactSpec(
        "store_area_sqm",
        "门店建筑面积和实际可经营面积分别多少平方米？",
        "影响租效、人员和品类适配。",
    ),
    "monthly_labor_cost": FactSpec(
        "monthly_labor_cost",
        "每月实际人工总成本多少，老板工资是否计入？",
        "构成固定成本和人效判断。",
        "工资表或排班表",
    ),
    "monthly_other_fixed_cost": FactSpec(
        "monthly_other_fixed_cost",
        "水电、贷款、软件、设备租赁等其他每月固定成本合计多少？",
        "补全保本计算。",
        "近三个月账单",
    ),
    "operating_days_per_month": FactSpec(
        "operating_days_per_month",
        "每月实际营业多少天？",
        "将日营业额换算成月度模型。",
    ),
    "expected_daily_revenue": FactSpec(
        "expected_daily_revenue",
        "预计日营业额多少元？",
        "用于检验开店模型是否覆盖保本线。",
    ),
    "revenue_basis": FactSpec(
        "revenue_basis",
        "预计营业额来自蹲点、竞品出单、历史门店，还是主观估计？",
        "决定收入假设的可信度。",
        "蹲点表、竞品订单记录或历史后台",
    ),
    "average_daily_revenue": FactSpec(
        "average_daily_revenue",
        "最近 30 天实际平均日营业额是多少元？",
        "形成当前经营基线。",
        "平台后台、收银或银行流水的脱敏截图",
    ),
    "contribution_margin_rate": FactSpec(
        "contribution_margin_rate",
        "扣除食材、包装、平台、折扣和损耗后的贡献毛利率是多少？",
        "决定每一元收入能覆盖多少固定成本。",
        "成本表和平台结算单",
    ),
    "remaining_cash": FactSpec(
        "remaining_cash",
        "当前可用于这家店继续经营的现金还有多少元？",
        "决定现金跑道。",
    ),
    "monthly_loss": FactSpec(
        "monthly_loss",
        "最近三个月平均每月实际亏损多少元？",
        "决定止损紧迫度并与模型计算交叉验证。",
        "月度损益或账目",
    ),
    "total_debt": FactSpec(
        "total_debt",
        "与门店相关的未偿债务合计多少元？",
        "决定现金流和退出风险。",
    ),
    "traffic_evidence": FactSpec(
        "traffic_evidence",
        "你记录过目标时段的经过人数、目标客群、进店人数和竞品出单吗？",
        "区分总人流与有效客流。",
        "带日期和时段的蹲点记录",
    ),
    "brand_name": FactSpec(
        "brand_name",
        "加盟品牌的完整名称是什么？",
        "用于当前品牌事实核验。",
    ),
    "contract_company_name": FactSpec(
        "contract_company_name",
        "合同签约公司的完整工商名称是什么？",
        "品牌名不能替代法律主体。",
        "合同首页或盖章页",
    ),
    "franchise_fee": FactSpec(
        "franchise_fee",
        "加盟、设备、装修、首批物料和保证金分别多少元？",
        "拆分不可回收投入和持续供货约束。",
        "费用清单",
    ),
    "direct_store_evidence": FactSpec(
        "direct_store_evidence",
        "亲自看过哪些直营店？地址、经营时长和目标时段客流如何？",
        "核验商业模式是否真实运行。",
        "实地记录，不能只使用总部样板材料",
    ),
    "contract_exit_terms": FactSpec(
        "contract_exit_terms",
        "合同中的供货、退款、违约、转让和退出条款分别怎么写？",
        "决定签约后的约束与退出成本。",
        "对应合同条款",
    ),
}


STAGE_FACTS: dict[Stage, tuple[str, ...]] = {
    Stage.PLANNED_OPENING: (
        "payment_or_signature_within_72h",
        "deposit_paid",
        "funding_type",
        "borrowed_amount",
        "maximum_affordable_loss",
        "location",
        "scene_type",
        "category",
        "target_period",
        "monthly_rent",
        "transfer_fee",
        "store_area_sqm",
        "monthly_labor_cost",
        "monthly_other_fixed_cost",
        "operating_days_per_month",
        "expected_daily_revenue",
        "revenue_basis",
        "contribution_margin_rate",
    ),
    Stage.SITE_SELECTION: (
        "payment_or_signature_within_72h",
        "deposit_paid",
        "location",
        "scene_type",
        "category",
        "target_period",
        "monthly_rent",
        "transfer_fee",
        "store_area_sqm",
        "monthly_labor_cost",
        "monthly_other_fixed_cost",
        "operating_days_per_month",
        "expected_daily_revenue",
        "revenue_basis",
        "contribution_margin_rate",
        "traffic_evidence",
    ),
    Stage.OPERATING_LOSS: (
        "remaining_cash",
        "monthly_loss",
        "total_debt",
        "location",
        "scene_type",
        "category",
        "target_period",
        "average_daily_revenue",
        "contribution_margin_rate",
        "monthly_rent",
        "monthly_labor_cost",
        "monthly_other_fixed_cost",
        "operating_days_per_month",
        "traffic_evidence",
    ),
    Stage.FRANCHISE: (
        "payment_or_signature_within_72h",
        "deposit_paid",
        "funding_type",
        "borrowed_amount",
        "maximum_affordable_loss",
        "brand_name",
        "contract_company_name",
        "franchise_fee",
        "direct_store_evidence",
        "contract_exit_terms",
        "location",
        "category",
    ),
}


CAPTURE_PREREQUISITES: dict[Stage, tuple[str, ...]] = {
    Stage.PLANNED_OPENING: ("location", "category", "target_period"),
    Stage.SITE_SELECTION: ("location", "category", "target_period"),
    Stage.OPERATING_LOSS: ("location", "category", "target_period"),
    Stage.FRANCHISE: (),
}


SAFETY_FACTS: dict[Stage, tuple[str, ...]] = {
    Stage.PLANNED_OPENING: (
        "payment_or_signature_within_72h",
        "deposit_paid",
        "funding_type",
    ),
    Stage.SITE_SELECTION: ("payment_or_signature_within_72h", "deposit_paid"),
    Stage.FRANCHISE: (
        "payment_or_signature_within_72h",
        "deposit_paid",
        "funding_type",
    ),
    Stage.OPERATING_LOSS: ("remaining_cash", "monthly_loss", "total_debt"),
}


ALLOWED: dict[Stage, tuple[Conclusion, ...]] = {
    Stage.PLANNED_OPENING: (
        Conclusion.PROCEED,
        Conclusion.PROCEED_WITH_CONDITIONS,
        Conclusion.DO_NOT_PROCEED,
        Conclusion.OBSERVE,
    ),
    Stage.SITE_SELECTION: (
        Conclusion.PROCEED_WITH_CONDITIONS,
        Conclusion.DO_NOT_PROCEED,
        Conclusion.OBSERVE,
    ),
    Stage.OPERATING_LOSS: (
        Conclusion.RECTIFY,
        Conclusion.OBSERVE,
        Conclusion.STOP_LOSS,
    ),
    Stage.FRANCHISE: (
        Conclusion.PROCEED_WITH_CONDITIONS,
        Conclusion.DO_NOT_PROCEED,
        Conclusion.OBSERVE,
    ),
}


CRITICAL_TOOLS: dict[Stage, frozenset[ToolName]] = {
    Stage.PLANNED_OPENING: frozenset(
        {ToolName.BUSINESS_CALCULATION, ToolName.VISUAL_ANALYSIS, ToolName.AMAP_COMPETITORS}
    ),
    Stage.SITE_SELECTION: frozenset(
        {ToolName.BUSINESS_CALCULATION, ToolName.VISUAL_ANALYSIS, ToolName.AMAP_COMPETITORS}
    ),
    Stage.OPERATING_LOSS: frozenset(
        {ToolName.BUSINESS_CALCULATION, ToolName.VISUAL_ANALYSIS}
    ),
    Stage.FRANCHISE: frozenset({ToolName.CURRENT_BUSINESS_LOOKUP}),
}


class RestaurantSkillProvider:
    def __init__(
        self,
        skill_path: str | Path | None = None,
        *,
        question_planner: QuestionPlanner | None = None,
    ) -> None:
        default = Path(__file__).resolve().parents[2] / "skill" / "restaurant-decision" / "SKILL.md"
        self.skill_path = Path(skill_path) if skill_path else default
        self.question_planner = question_planner

    def system_instructions(self) -> str:
        return self.skill_path.read_text(encoding="utf-8")

    def next_directive(self, snapshot: SessionSnapshot) -> SkillDirective:
        warning = self._safety_warning(snapshot)
        missing = self._missing_fact_keys(snapshot)

        for key in SAFETY_FACTS[snapshot.stage]:
            if key in missing:
                spec = FACT_SPECS[key]
                return SkillDirective(
                    action=NextAction.ASK,
                    message=spec.question,
                    missing_facts=missing,
                    warning=warning,
                    rationale_codes=("deterministic_safety_gate", key),
                )

        capture_prerequisites = CAPTURE_PREREQUISITES[snapshot.stage]
        capture_ready = all(self._present(snapshot.value(key)) for key in capture_prerequisites)
        if capture_prerequisites and capture_ready and not self._present(snapshot.value("site_media_refs")):
            return SkillDirective(
                action=NextAction.REQUEST_CAPTURE,
                message="请在目标营业时段按拍摄清单补充门店与周边视频。",
                tool_arguments={"checklist": capture_checklist()},
                missing_facts=missing,
                warning=warning,
                rationale_codes=("site_claim_needs_visual_evidence",),
            )

        required_tools = self._required_tools(snapshot)
        for tool in required_tools:
            if snapshot.result(tool) is not None or not self._tool_ready(snapshot, tool):
                continue
            if tool in snapshot.available_tools:
                return SkillDirective(
                    action=NextAction.CALL_TOOL,
                    message=self._tool_message(tool),
                    tool_name=tool,
                    tool_arguments=self._tool_arguments(snapshot, tool),
                    missing_facts=missing,
                    warning=warning,
                    rationale_codes=("ready_evidence_before_more_questions", tool.value),
                )

        if missing:
            return self._plan_question(snapshot, missing, warning)

        unavailable: list[ToolName] = []
        invalid: list[ToolName] = []
        for tool in required_tools:
            result = snapshot.result(tool)
            if result is None:
                if tool in snapshot.available_tools:
                    return SkillDirective(
                        action=NextAction.CALL_TOOL,
                        message=self._tool_message(tool),
                        tool_name=tool,
                        tool_arguments=self._tool_arguments(snapshot, tool),
                        warning=warning,
                        rationale_codes=("evidence_required", tool.value),
                    )
                unavailable.append(tool)
                continue
            if not self._valid_result(tool, result):
                invalid.append(tool)

        unavailable.extend(item for item in invalid if item not in unavailable)
        critical_failure = CRITICAL_TOOLS[snapshot.stage].intersection(unavailable)
        if critical_failure:
            return SkillDirective(
                action=NextAction.READY_FOR_JUDGMENT,
                message=(
                    "关键证据工具不可用或返回无效结果，只能说明证据不足并给出低风险补证动作，"
                    "不得给继续投入、关店或签约结论。"
                ),
                allowed_conclusions=(Conclusion.INSUFFICIENT_EVIDENCE,),
                warning=warning,
                unavailable_tools=tuple(unavailable),
                rationale_codes=("critical_evidence_unavailable",),
            )

        return SkillDirective(
            action=NextAction.READY_FOR_JUDGMENT,
            message=(
                "证据达到结构化判断门槛。模型必须引用真实 evidence ID，同时列出反证、"
                "关键缺口、第一动作、验证条件和停止条件。"
            ),
            allowed_conclusions=ALLOWED[snapshot.stage],
            warning=warning,
            unavailable_tools=tuple(unavailable),
            rationale_codes=("minimum_evidence_gate_passed", "judgment_validator_required"),
        )

    def _plan_question(
        self,
        snapshot: SessionSnapshot,
        missing: tuple[str, ...],
        warning: str | None,
    ) -> SkillDirective:
        candidates = tuple(FACT_SPECS[key].candidate() for key in missing)
        if self.question_planner is None:
            return SkillDirective(
                action=NextAction.PLAN_QUESTION,
                message=(
                    "必须由语言模型根据当前假设、反证和决策影响选择一个下一问；"
                    "不要按候选列表顺序机械选择。"
                ),
                missing_facts=missing,
                question_candidates=candidates,
                warning=warning,
                rationale_codes=("semantic_question_planner_required",),
            )
        selection = self.question_planner.select(snapshot, candidates)
        return SkillDirective(
            action=NextAction.ASK,
            message=selection.question,
            missing_facts=missing,
            question_candidates=candidates,
            warning=warning,
            rationale_codes=("model_selected_high_information_question", selection.fact_key),
        )

    @staticmethod
    def _present(value: Any) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, dict)):
            return bool(value)
        return True

    def _missing_fact_keys(self, snapshot: SessionSnapshot) -> tuple[str, ...]:
        return tuple(
            key for key in STAGE_FACTS[snapshot.stage] if not self._present(snapshot.value(key))
        )

    @staticmethod
    def _safety_warning(snapshot: SessionSnapshot) -> str | None:
        imminent = snapshot.value("payment_or_signature_within_72h") is True
        funding_type = str(snapshot.value("funding_type", "")).strip().lower()
        leveraged = funding_type in {"borrowed", "loan", "mortgage", "借款", "贷款", "抵押"}
        if imminent or leveraged:
            return (
                "在事实核验完成前，暂停新增付款、签字和不可逆承诺；"
                "这是临时安全动作，不是最终经营结论。"
            )
        return None

    @staticmethod
    def _required_tools(snapshot: SessionSnapshot) -> tuple[ToolName, ...]:
        tools: list[ToolName] = []
        if snapshot.user_id and snapshot.store_id:
            tools.append(ToolName.STORE_PROFILE)
        if snapshot.stage in {Stage.PLANNED_OPENING, Stage.SITE_SELECTION, Stage.OPERATING_LOSS}:
            tools.extend((ToolName.BUSINESS_CALCULATION, ToolName.VISUAL_ANALYSIS))
        if snapshot.has_private_knowledge:
            tools.append(ToolName.PRIVATE_RAG)
        tools.append(ToolName.PLATFORM_RAG)
        if snapshot.stage in {Stage.PLANNED_OPENING, Stage.SITE_SELECTION}:
            tools.append(ToolName.AMAP_COMPETITORS)
        if snapshot.stage == Stage.FRANCHISE:
            tools.append(ToolName.CURRENT_BUSINESS_LOOKUP)
        return tuple(tools)

    @staticmethod
    def _tool_ready(snapshot: SessionSnapshot, tool: ToolName) -> bool:
        if tool == ToolName.STORE_PROFILE:
            return all(
                RestaurantSkillProvider._present(value)
                for value in (snapshot.user_id, snapshot.store_id)
            )
        if tool == ToolName.BUSINESS_CALCULATION:
            common = (
                "operating_days_per_month",
                "contribution_margin_rate",
                "monthly_rent",
                "monthly_labor_cost",
                "monthly_other_fixed_cost",
            )
            revenue_key = (
                "average_daily_revenue"
                if snapshot.stage == Stage.OPERATING_LOSS
                else "expected_daily_revenue"
            )
            return all(
                RestaurantSkillProvider._present(snapshot.value(key))
                for key in (*common, revenue_key)
            )
        if tool == ToolName.VISUAL_ANALYSIS:
            return RestaurantSkillProvider._present(snapshot.value("site_media_refs"))
        if tool == ToolName.PRIVATE_RAG:
            return snapshot.has_private_knowledge and RestaurantSkillProvider._present(snapshot.user_id)
        if tool == ToolName.PLATFORM_RAG:
            return RestaurantSkillProvider._present(snapshot.value("category"))
        if tool == ToolName.AMAP_COMPETITORS:
            return all(
                RestaurantSkillProvider._present(snapshot.value(key))
                for key in ("location", "category")
            )
        if tool == ToolName.CURRENT_BUSINESS_LOOKUP:
            return all(
                RestaurantSkillProvider._present(snapshot.value(key))
                for key in ("brand_name", "contract_company_name")
            )
        return True

    @staticmethod
    def _tool_message(tool: ToolName) -> str:
        return {
            ToolName.BUSINESS_CALCULATION: "调用确定性经营计算，生成保本线、利润和现金跑道证据。",
            ToolName.VISUAL_ANALYSIS: "调用多模态模型分析店铺视频，严格分开画面观察与经营推断。",
            ToolName.PRIVATE_RAG: "检索当前用户自己的历史材料，必须校验 user_id。",
            ToolName.PLATFORM_RAG: "检索经过审核的方法卡和相似案例，并返回来源与审核等级。",
            ToolName.AMAP_COMPETITORS: "核验当前周边同类 POI；POI 数量不得替代真实客流。",
            ToolName.CURRENT_BUSINESS_LOOKUP: "核验当前公司、品牌、备案、处罚或诉讼事实。",
            ToolName.STORE_PROFILE: "读取当前用户的门店状态。",
        }[tool]

    @staticmethod
    def _tool_arguments(snapshot: SessionSnapshot, tool: ToolName) -> dict[str, Any]:
        if tool == ToolName.STORE_PROFILE:
            return {"user_id": snapshot.user_id, "store_id": snapshot.store_id}
        if tool == ToolName.BUSINESS_CALCULATION:
            keys = (
                "average_daily_revenue",
                "expected_daily_revenue",
                "operating_days_per_month",
                "contribution_margin_rate",
                "monthly_rent",
                "monthly_labor_cost",
                "monthly_other_fixed_cost",
                "remaining_cash",
            )
            return {key: snapshot.value(key) for key in keys if snapshot.fact(key) is not None}
        if tool == ToolName.VISUAL_ANALYSIS:
            return {
                "media_refs": snapshot.value("site_media_refs"),
                "stage": snapshot.stage.value,
                "category": snapshot.value("category"),
                "target_period": snapshot.value("target_period"),
            }
        if tool == ToolName.PRIVATE_RAG:
            return {
                "user_id": snapshot.user_id,
                "query": RestaurantSkillProvider._query_text(snapshot),
                "stage": snapshot.stage.value,
                "top_k": 3,
            }
        if tool == ToolName.PLATFORM_RAG:
            return {
                "query": RestaurantSkillProvider._query_text(snapshot),
                "stage": snapshot.stage.value,
                "top_k": 5,
                "minimum_evidence_grade": "reviewed",
            }
        if tool == ToolName.AMAP_COMPETITORS:
            return {"location": snapshot.value("location"), "category": snapshot.value("category")}
        if tool == ToolName.CURRENT_BUSINESS_LOOKUP:
            return {
                "brand_name": snapshot.value("brand_name"),
                "company_name": snapshot.value("contract_company_name"),
            }
        return {}

    @staticmethod
    def _query_text(snapshot: SessionSnapshot) -> str:
        keys = (
            "location",
            "scene_type",
            "category",
            "average_daily_revenue",
            "expected_daily_revenue",
            "monthly_rent",
            "traffic_evidence",
            "revenue_basis",
            "brand_name",
        )
        values = [str(snapshot.value(key, "")).strip() for key in keys]
        return "；".join(value for value in values if value)

    @staticmethod
    def _valid_result(tool: ToolName, result: ToolResult) -> bool:
        if result.status == ToolStatus.NO_HIT:
            return bool(result.source) and tool not in {
                ToolName.BUSINESS_CALCULATION,
                ToolName.VISUAL_ANALYSIS,
                ToolName.CURRENT_BUSINESS_LOOKUP,
            }
        if not result.has_usable_evidence:
            return False
        if tool == ToolName.BUSINESS_CALCULATION:
            return "break_even_daily_revenue" in result.data
        if tool == ToolName.VISUAL_ANALYSIS:
            return bool(result.data.get("observations"))
        return True


