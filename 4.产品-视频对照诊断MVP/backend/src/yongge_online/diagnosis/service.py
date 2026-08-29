from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from yongge_online.ai.ports import ReportGeneratorPort
from yongge_online.core.errors import DomainError, NotFoundError
from yongge_online.db.models import (
    DiagnosisSession,
    ReportRecord,
    SessionEvent,
    Store,
    ToolCall,
)
from yongge_online.diagnosis.schemas import (
    DiagnosisConclusion,
    DiagnosisReport,
    SessionEventCreate,
    ToolExecuteRequest,
)
from yongge_online.knowledge.platform import (
    DatabasePlatformKnowledgeRetriever,
    PlatformKnowledgeService,
)
from yongge_online.knowledge.ports import (
    KnowledgeRetrieverPort,
    PlatformKnowledgeRetrieverPort,
)
from yongge_online.knowledge.service import DatabaseKnowledgeRetriever, KnowledgeService
from yongge_online.skills.assist import (
    compose_assist_message,
    extract_metric_updates,
    should_query_kb,
)
from yongge_online.skills.ports import (
    SkillAdvanceRequest,
    SkillAdvanceResult,
    SkillDirective,
    SkillEnginePort,
    SkillSessionContext,
)
from yongge_online.tools.map_provider import MapProviderPort
from yongge_online.tools.registry import ToolRegistry
from yongge_online.tools.schemas import StoreSnapshot

PrivateRetrieverFactory = Callable[[AsyncSession], KnowledgeRetrieverPort]
PlatformRetrieverFactory = Callable[[AsyncSession], PlatformKnowledgeRetrieverPort]


class DiagnosisService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        report_provider: ReportGeneratorPort,
        map_provider: MapProviderPort,
        private_retriever_factory: PrivateRetrieverFactory | None = None,
        platform_retriever_factory: PlatformRetrieverFactory | None = None,
    ):
        self.session = session
        self.report_provider = report_provider
        self.map_provider = map_provider
        self.private_retriever_factory = (
            private_retriever_factory or DatabaseKnowledgeRetriever
        )
        self.platform_retriever_factory = (
            platform_retriever_factory or DatabasePlatformKnowledgeRetriever
        )

    async def create_session(self, store_id: str) -> DiagnosisSession:
        store = await self.session.get(Store, store_id)
        if store is None:
            raise NotFoundError("门店")
        snapshot = StoreSnapshot.model_validate(store)
        diagnosis = DiagnosisSession(
            id=str(uuid4()),
            user_id=store.user_id,
            store_id=store.id,
            status="created",
            store_snapshot_json=snapshot.model_dump(mode="json"),
        )
        self.session.add(diagnosis)
        await self.session.commit()
        await self.session.refresh(diagnosis)
        return diagnosis

    async def get_session(self, session_id: str) -> DiagnosisSession:
        diagnosis = await self.session.get(DiagnosisSession, session_id)
        if diagnosis is None:
            raise NotFoundError("诊断会话")
        return diagnosis

    async def list_sessions(self, *, limit: int = 20) -> list[DiagnosisSession]:
        return list(
            await self.session.scalars(
                select(DiagnosisSession)
                .order_by(DiagnosisSession.created_at.desc())
                .limit(limit)
            )
        )

    async def list_events(self, session_id: str) -> list[SessionEvent]:
        await self.get_session(session_id)
        return list(
            await self.session.scalars(
                select(SessionEvent)
                .where(SessionEvent.session_id == session_id)
                .order_by(SessionEvent.sequence)
            )
        )

    async def add_event(
        self,
        session_id: str,
        payload: SessionEventCreate,
    ) -> SessionEvent:
        diagnosis = await self.get_session(session_id)
        if diagnosis.status == "completed":
            raise DomainError("已完成会话不能追加事件", code="session_completed", status_code=409)
        current_max = await self.session.scalar(
            select(func.max(SessionEvent.sequence)).where(SessionEvent.session_id == session_id)
        )
        event = SessionEvent(
            id=str(uuid4()),
            session_id=session_id,
            sequence=(current_max or 0) + 1,
            event_type=payload.event_type,
            actor=payload.actor,
            payload_json=payload.payload,
        )
        diagnosis.status = "active"
        if diagnosis.started_at is None:
            diagnosis.started_at = datetime.now(UTC)
        self.session.add(event)
        await self.session.commit()
        await self.session.refresh(event)
        return event

    async def execute_tool(
        self,
        session_id: str,
        payload: ToolExecuteRequest,
    ) -> ToolCall:
        diagnosis = await self.get_session(session_id)
        existing = await self.session.scalar(
            select(ToolCall).where(
                ToolCall.session_id == session_id,
                ToolCall.call_id == payload.call_id,
            )
        )
        if existing is not None:
            return existing

        store = StoreSnapshot.model_validate(diagnosis.store_snapshot_json)
        registry = ToolRegistry(
            store=store,
            retriever=self.private_retriever_factory(self.session),
            platform_retriever=self.platform_retriever_factory(self.session),
            map_provider=self.map_provider,
        )
        started = perf_counter()
        result = await registry.execute(payload.tool_name, payload.arguments)
        duration_ms = max(0, round((perf_counter() - started) * 1000))
        tool_call = ToolCall(
            id=str(uuid4()),
            session_id=session_id,
            call_id=payload.call_id,
            tool_name=payload.tool_name,
            arguments_json=payload.arguments,
            result_json=result,
            status="completed",
            duration_ms=duration_ms,
        )
        diagnosis.status = "active"
        if diagnosis.started_at is None:
            diagnosis.started_at = datetime.now(UTC)
        self.session.add(tool_call)
        await self.session.commit()
        await self.session.refresh(tool_call)
        return tool_call

    async def advance_skill(
        self,
        session_id: str,
        payload: SkillAdvanceRequest,
        skill_engine: SkillEnginePort,
    ) -> SkillAdvanceResult:
        diagnosis = await self.get_session(session_id)
        events = list(
            await self.session.scalars(
                select(SessionEvent)
                .where(SessionEvent.session_id == session_id)
                .order_by(SessionEvent.sequence)
            )
        )
        tool_calls = list(
            await self.session.scalars(
                select(ToolCall)
                .where(ToolCall.session_id == session_id)
                .order_by(ToolCall.created_at, ToolCall.id)
            )
        )
        private_knowledge = await KnowledgeService(self.session).list_for_store(
            diagnosis.store_id
        )
        context = SkillSessionContext(
            session_id=diagnosis.id,
            user_id=diagnosis.user_id,
            store=StoreSnapshot.model_validate(diagnosis.store_snapshot_json),
            facts=payload.facts,
            evidence=payload.evidence,
            hypotheses=payload.hypotheses,
            events=[
                {
                    "id": item.id,
                    "sequence": item.sequence,
                    "event_type": item.event_type,
                    "actor": item.actor,
                    "payload": item.payload_json,
                }
                for item in events
            ],
            tool_calls=[
                {
                    "id": item.id,
                    "call_id": item.call_id,
                    "tool_name": item.tool_name,
                    "arguments": item.arguments_json,
                    "result": item.result_json,
                    "status": item.status,
                }
                for item in tool_calls
            ],
            has_private_knowledge=bool(private_knowledge),
        )
        # 服务端确定性辅助:实测模型不会自主调工具(0/12 场,PRD §23 2026-07-23),
        # 故由服务端机械触发计算/检索,结果经 execute_tool 落 tool_calls 表(可测量)。
        assist_result = await self._server_assist(session_id, context.store, payload)
        if assist_result is not None:
            result = assist_result
        else:
            result = SkillAdvanceResult.model_validate(
                await skill_engine.advance(context)
            )
        # 空指令(无话可注入)不落事件,避免污染会话记录与报告底料
        if result.directive.message or result.tool_results:
            await self.add_event(
                session_id,
                SessionEventCreate(
                    event_type="skill_directive",
                    actor="system",
                    payload=result.model_dump(mode="json"),
                ),
            )
        return result

    async def _server_assist(
        self,
        session_id: str,
        store: StoreSnapshot,
        payload: SkillAdvanceRequest,
    ) -> SkillAdvanceResult | None:
        utterance = str(payload.facts.get("latest_user_utterance") or "").strip()
        if not utterance:
            return None
        tool_results: dict[str, dict[str, Any]] = {}
        updates = extract_metric_updates(utterance)
        metrics_payload: dict[str, Any] | None = None
        if updates:
            call = await self.execute_tool(
                session_id,
                ToolExecuteRequest(
                    call_id=f"assist-calc-{uuid4().hex[:12]}",
                    tool_name="calculate_business_metrics",
                    arguments=updates,
                ),
            )
            metrics_payload = call.result_json
            tool_results["calculate_business_metrics"] = metrics_payload
        kb_payload: dict[str, Any] | None = None
        if should_query_kb(utterance):
            call = await self.execute_tool(
                session_id,
                ToolExecuteRequest(
                    call_id=f"assist-rag-{uuid4().hex[:12]}",
                    tool_name="platform_rag",
                    arguments={
                        "query": utterance,
                        "limit": 2,
                        "category": store.category,
                        "stage": store.stage,
                    },
                ),
            )
            if call.result_json.get("status") == "ok":
                kb_payload = call.result_json
                tool_results["platform_rag"] = kb_payload
        message = compose_assist_message(updates, metrics_payload, kb_payload)
        if not message:
            return None
        return SkillAdvanceResult(
            directive=SkillDirective(
                action="ask",
                message=message,
                rationale_codes=["server_assist"],
            ),
            tool_results=tool_results,
        )

    async def complete(self, session_id: str) -> ReportRecord:
        diagnosis = await self.get_session(session_id)
        existing = await self.session.scalar(
            select(ReportRecord).where(ReportRecord.session_id == session_id)
        )
        if existing is not None:
            return existing

        context = await self._build_report_context(diagnosis)
        is_fallback = False
        try:
            report = await self.report_provider.generate_report(context=context)
            report = self._strip_fabricated_evidence(report, context)
            self._validate_evidence(report, context)
        except Exception as exc:
            is_fallback = True
            report = self._fallback_report(exc)
        report = self._enforce_stage_conclusion(
            report,
            StoreSnapshot.model_validate(diagnosis.store_snapshot_json),
        )

        record = ReportRecord(
            id=str(uuid4()),
            session_id=session_id,
            version=1,
            report_json=report.model_dump(mode="json"),
            is_fallback=is_fallback,
        )
        diagnosis.status = "completed"
        diagnosis.ended_at = datetime.now(UTC)
        self.session.add(record)
        await self.session.commit()
        await self.session.refresh(record)
        return record

    async def get_report(self, session_id: str) -> ReportRecord:
        await self.get_session(session_id)
        report = await self.session.scalar(
            select(ReportRecord).where(ReportRecord.session_id == session_id)
        )
        if report is None:
            raise NotFoundError("复盘报告")
        return report

    async def _build_report_context(self, diagnosis: DiagnosisSession) -> dict[str, Any]:
        events = list(
            await self.session.scalars(
                select(SessionEvent)
                .where(SessionEvent.session_id == diagnosis.id)
                .order_by(SessionEvent.sequence)
            )
        )
        tool_calls = list(
            await self.session.scalars(
                select(ToolCall)
                .where(ToolCall.session_id == diagnosis.id)
                .order_by(ToolCall.created_at, ToolCall.id)
            )
        )
        knowledge = await KnowledgeService(self.session).list_for_store(diagnosis.store_id)
        platform_evidence_ids = [
            str(evidence_id)
            for item in tool_calls
            if item.tool_name == "platform_rag" and item.status == "completed"
            for evidence_id in item.result_json.get("evidence_ids", [])
            if evidence_id
        ]
        platform_knowledge = await PlatformKnowledgeService(self.session).get_many(
            platform_evidence_ids
        )
        return {
            "session_id": diagnosis.id,
            "store": diagnosis.store_snapshot_json,
            "events": [
                {
                    "id": item.id,
                    "sequence": item.sequence,
                    "event_type": item.event_type,
                    "actor": item.actor,
                    "payload": item.payload_json,
                }
                for item in events
            ],
            "tool_calls": [
                {
                    "id": item.id,
                    "tool_name": item.tool_name,
                    "arguments": item.arguments_json,
                    "result": item.result_json,
                }
                for item in tool_calls
            ],
            "knowledge": [
                {
                    "id": item.id,
                    "scope": "private",
                    "kind": item.kind,
                    "content": item.content,
                    "tags": item.tags_json,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                }
                for item in knowledge
            ]
            + [
                {
                    "id": item.id,
                    "scope": "platform",
                    "source_type": item.source_type,
                    "source_id": item.source_id,
                    "source_uri": item.source_uri,
                    "kind": item.kind,
                    "content": item.content,
                    "tags": item.tags_json,
                    "start_ms": item.start_ms,
                    "end_ms": item.end_ms,
                    "review_status": item.review_status,
                }
                for item in platform_knowledge
            ],
        }

    @staticmethod
    def _strip_fabricated_evidence(
        report: DiagnosisReport, context: dict[str, Any]
    ) -> DiagnosisReport:
        """剥掉编造/抄错的证据引用,保留判断本身(校准式护栏,见 PRD §23 2026-07-22 决策)。

        - 引用真实存在 → 保留;
        - 引用不存在 → 剥除该条引用;
        - 某问题的引用被剥光 → 丢弃该问题(它的证据全是编的);
        - 发生剥除时在 information_gaps 里透明记录,不整报告降级。
        """
        allowed = {
            "knowledge_item": {item["id"] for item in context["knowledge"]},
            "tool_call": {item["id"] for item in context["tool_calls"]},
            "session_event": {item["id"] for item in context["events"]},
        }
        kept_problems = []
        stripped_refs = 0
        dropped_problems = 0
        for problem in report.problems:
            valid_refs = [
                ref
                for ref in problem.evidence_refs
                if ref.source_id in allowed.get(ref.source_type, set())
            ]
            removed = len(problem.evidence_refs) - len(valid_refs)
            if removed == 0:
                kept_problems.append(problem)
            elif valid_refs:
                stripped_refs += removed
                kept_problems.append(
                    problem.model_copy(update={"evidence_refs": valid_refs})
                )
            else:
                dropped_problems += 1
        if stripped_refs or dropped_problems:
            notes = []
            if stripped_refs:
                notes.append(f"已剥除 {stripped_refs} 处无法核验的证据引用")
            if dropped_problems:
                notes.append(f"已丢弃 {dropped_problems} 个证据全部无法核验的问题")
            report = report.model_copy(
                update={
                    "problems": kept_problems,
                    "information_gaps": [*report.information_gaps, *notes],
                }
            )
        return report

    # 结论词表按阶段的确定性硬门(prompt 只是软约束):
    # 店还没开(planning/opening)谈不上整改/观察经营/止损;已在营则反之。
    # 越权结论按语义强度就近映射,并把校准记入 information_gaps(透明可审计)。
    _PRE_OPEN_STAGES = frozenset({"planning", "opening"})
    _PRE_OPEN_ALLOWED = frozenset(
        {
            DiagnosisConclusion.PROCEED,
            DiagnosisConclusion.CONDITIONAL_PROCEED,
            DiagnosisConclusion.DO_NOT_PROCEED,
            DiagnosisConclusion.INSUFFICIENT_DATA,
        }
    )
    _OPERATING_ALLOWED = frozenset(
        {
            DiagnosisConclusion.RECTIFY,
            DiagnosisConclusion.OBSERVE,
            DiagnosisConclusion.STOP_LOSS,
            DiagnosisConclusion.INSUFFICIENT_DATA,
        }
    )
    _TO_PRE_OPEN = {
        DiagnosisConclusion.RECTIFY: DiagnosisConclusion.CONDITIONAL_PROCEED,
        DiagnosisConclusion.OBSERVE: DiagnosisConclusion.CONDITIONAL_PROCEED,
        DiagnosisConclusion.STOP_LOSS: DiagnosisConclusion.DO_NOT_PROCEED,
    }
    _TO_OPERATING = {
        DiagnosisConclusion.PROCEED: DiagnosisConclusion.OBSERVE,
        DiagnosisConclusion.CONDITIONAL_PROCEED: DiagnosisConclusion.RECTIFY,
        DiagnosisConclusion.DO_NOT_PROCEED: DiagnosisConclusion.STOP_LOSS,
    }

    @classmethod
    def _enforce_stage_conclusion(
        cls, report: DiagnosisReport, store: StoreSnapshot
    ) -> DiagnosisReport:
        pre_open = store.stage in cls._PRE_OPEN_STAGES
        allowed = cls._PRE_OPEN_ALLOWED if pre_open else cls._OPERATING_ALLOWED
        if report.conclusion in allowed:
            return report
        remap = cls._TO_PRE_OPEN if pre_open else cls._TO_OPERATING
        mapped = remap.get(report.conclusion, DiagnosisConclusion.INSUFFICIENT_DATA)
        note = (
            f"结论已按门店阶段校准：原判「{report.conclusion}」对 stage="
            f"{store.stage} 越权，映射为「{mapped}」"
        )
        return report.model_copy(
            update={
                "conclusion": mapped,
                "information_gaps": [*report.information_gaps, note],
            }
        )

    @staticmethod
    def _validate_evidence(report: DiagnosisReport, context: dict[str, Any]) -> None:
        allowed = {
            "knowledge_item": {item["id"] for item in context["knowledge"]},
            "tool_call": {item["id"] for item in context["tool_calls"]},
            "session_event": {item["id"] for item in context["events"]},
        }
        for problem in report.problems:
            for reference in problem.evidence_refs:
                if reference.source_id not in allowed[reference.source_type]:
                    raise ValueError(
                        f"report references unknown {reference.source_type}: "
                        f"{reference.source_id}"
                    )

    @staticmethod
    def _fallback_report(error: Exception) -> DiagnosisReport:
        return DiagnosisReport(
            summary="AI 报告暂不可用，已保存全部事实和工具结果供稍后重试。",
            conclusion=DiagnosisConclusion.INSUFFICIENT_DATA,
            confidence=0,
            problems=[],
            immediate_actions=[],
            short_term_actions=[],
            observation_metrics=[],
            information_gaps=[f"报告生成失败：{error}"],
        )


