from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from yongge_online.tools.schemas import StoreSnapshot


class SkillContext(BaseModel):
    session_id: str
    store: StoreSnapshot
    # 连麦前上下文:案例解析摘要 + 四维解构初判(有已解析视频时注入,专家不重复问已知信息)
    case_context: dict[str, Any] | None = None


class SkillAdvanceRequest(BaseModel):
    facts: dict[str, Any] = Field(default_factory=dict)
    evidence: dict[str, Any] = Field(default_factory=dict)
    hypotheses: list[dict[str, Any]] = Field(default_factory=list)


class SkillSessionContext(BaseModel):
    session_id: str
    user_id: str
    store: StoreSnapshot
    facts: dict[str, Any]
    evidence: dict[str, Any]
    hypotheses: list[dict[str, Any]]
    events: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    has_private_knowledge: bool


class SkillDirective(BaseModel):
    action: Literal[
        "ask",
        "plan_question",
        "request_capture",
        "call_tool",
        "ready_for_judgment",
    ]
    message: str
    missing_facts: list[str] = Field(default_factory=list)
    question_candidates: list[dict[str, Any]] = Field(default_factory=list)
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    allowed_conclusions: list[str] = Field(default_factory=list)
    warning: str | None = None
    unavailable_tools: list[str] = Field(default_factory=list)
    rationale_codes: list[str] = Field(default_factory=list)


class SkillAdvanceResult(BaseModel):
    directive: SkillDirective
    tool_results: dict[str, dict[str, Any]] = Field(default_factory=dict)
    trace: list[dict[str, Any]] = Field(default_factory=list)


class SkillEnginePort(Protocol):
    async def build_session_instructions(self, context: SkillContext) -> str: ...

    async def advance(
        self,
        context: SkillSessionContext,
    ) -> SkillAdvanceResult | dict[str, Any]: ...


