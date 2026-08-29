from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DiagnosisStatus(StrEnum):
    CREATED = "created"
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"


class DiagnosisConclusion(StrEnum):
    # 开店前(planning/opening)词表——店还没开,谈不上整改/止损
    PROCEED = "proceed"
    CONDITIONAL_PROCEED = "conditional_proceed"
    DO_NOT_PROCEED = "do_not_proceed"
    # 已在营(operating/closing)词表
    RECTIFY = "rectify"
    OBSERVE = "observe"
    STOP_LOSS = "stop_loss"
    # 两个阶段都合法
    INSUFFICIENT_DATA = "insufficient_data"


class DiagnosisSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    store_id: str
    status: DiagnosisStatus
    store_snapshot_json: dict[str, Any]
    started_at: datetime | None
    ended_at: datetime | None
    created_at: datetime


class SessionEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    actor: Literal["user", "assistant", "system", "tool"]
    payload: dict[str, Any]


class SessionEventRead(BaseModel):
    id: str
    session_id: str
    sequence: int
    event_type: str
    actor: str
    payload: dict[str, Any]
    created_at: datetime


class ToolExecuteRequest(BaseModel):
    call_id: str = Field(min_length=1, max_length=120)
    tool_name: str = Field(min_length=1, max_length=80)
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolCallRead(BaseModel):
    id: str
    session_id: str
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any]
    status: str
    duration_ms: int
    created_at: datetime


class EvidenceRef(BaseModel):
    source_type: Literal["knowledge_item", "tool_call", "session_event"]
    source_id: str
    description: str = Field(min_length=1)


class ProblemFinding(BaseModel):
    title: str = Field(min_length=1)
    priority: Literal["P0", "P1", "P2"]
    category: Literal[
        "revenue",
        "cost",
        "product",
        "people",
        "marketing",
        "location",
        "cashflow",
        "other",
    ]
    rationale: str = Field(min_length=1)
    evidence_refs: list[EvidenceRef] = Field(min_length=1)


class ActionItem(BaseModel):
    title: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    steps: list[str] = Field(min_length=1)
    success_metric: str = Field(min_length=1)


class DiagnosisReport(BaseModel):
    summary: str = Field(min_length=1)
    conclusion: DiagnosisConclusion
    confidence: float = Field(ge=0, le=1)
    problems: list[ProblemFinding] = Field(default_factory=list)
    immediate_actions: list[ActionItem] = Field(default_factory=list)
    short_term_actions: list[ActionItem] = Field(default_factory=list)
    observation_metrics: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)


class ReportRead(BaseModel):
    id: str
    session_id: str
    version: int
    report: DiagnosisReport
    is_fallback: bool
    created_at: datetime


