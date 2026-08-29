from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence


class Stage(str, Enum):
    PLANNED_OPENING = "planned_opening"
    OPERATING_LOSS = "operating_loss"
    FRANCHISE = "franchise"
    SITE_SELECTION = "site_selection"


class EvidenceKind(str, Enum):
    REPORTED = "reported_fact"
    OBSERVED = "observed_fact"
    TOOL = "tool_fact"
    INFERENCE = "inference"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    USER_CONFIRMED = "user_confirmed"
    ARTIFACT_VERIFIED = "artifact_verified"
    TOOL_VERIFIED = "tool_verified"
    CONFLICTED = "conflicted"


class ToolStatus(str, Enum):
    OK = "ok"
    NO_HIT = "no_hit"
    UNAVAILABLE = "unavailable"
    FORBIDDEN = "forbidden"
    INVALID_INPUT = "invalid_input"
    INVALID_RESULT = "invalid_result"


class ToolName(str, Enum):
    BUSINESS_CALCULATION = "business_calculation"
    AMAP_COMPETITORS = "amap_competitors"
    PLATFORM_RAG = "platform_rag"
    PRIVATE_RAG = "private_rag"
    VISUAL_ANALYSIS = "visual_analysis"
    CURRENT_BUSINESS_LOOKUP = "current_business_lookup"
    STORE_PROFILE = "store_profile"


class NextAction(str, Enum):
    ASK = "ask"
    PLAN_QUESTION = "plan_question"
    REQUEST_CAPTURE = "request_capture"
    CALL_TOOL = "call_tool"
    READY_FOR_JUDGMENT = "ready_for_judgment"


class Conclusion(str, Enum):
    PROCEED = "proceed"
    PROCEED_WITH_CONDITIONS = "proceed_with_conditions"
    DO_NOT_PROCEED = "do_not_proceed"
    RECTIFY = "rectify"
    OBSERVE = "observe"
    STOP_LOSS = "stop_loss"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


@dataclass(frozen=True)
class FactRecord:
    """One atomic fact. Compound prose belongs in notes, not in ``value``."""

    key: str
    value: Any
    kind: EvidenceKind = EvidenceKind.REPORTED
    verification: VerificationStatus = VerificationStatus.UNVERIFIED
    evidence_ids: tuple[str, ...] = ()
    source: str | None = None
    observed_at: str | None = None
    unit: str | None = None

    @classmethod
    def from_value(cls, key: str, value: Any) -> "FactRecord":
        if isinstance(value, cls):
            return value
        return cls(key=key, value=value)


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    kind: EvidenceKind
    source: str
    summary: str
    locator: str | None = None
    observed_at: str | None = None
    confidence: float | None = None

    def __post_init__(self) -> None:
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class ToolResult:
    status: ToolStatus
    evidence_ids: tuple[str, ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""
    error_code: str | None = None

    @classmethod
    def from_value(cls, value: "ToolResult | Mapping[str, Any]") -> "ToolResult":
        if isinstance(value, cls):
            return value
        try:
            status = ToolStatus(value.get("status", ToolStatus.INVALID_RESULT.value))
        except ValueError:
            status = ToolStatus.INVALID_RESULT
        evidence_ids = tuple(str(item) for item in value.get("evidence_ids", ()) if item)
        data = value.get("data", {})
        if not isinstance(data, Mapping):
            data = {}
            status = ToolStatus.INVALID_RESULT
        return cls(
            status=status,
            evidence_ids=evidence_ids,
            data=data,
            source=str(value.get("source", "")),
            error_code=value.get("error_code"),
        )

    @property
    def is_success(self) -> bool:
        return self.status in {ToolStatus.OK, ToolStatus.NO_HIT}

    @property
    def has_usable_evidence(self) -> bool:
        if self.status == ToolStatus.NO_HIT:
            return bool(self.source)
        return self.status == ToolStatus.OK and bool(self.evidence_ids) and bool(self.source)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "evidence_ids": list(self.evidence_ids),
            "data": dict(self.data),
            "source": self.source,
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class Hypothesis:
    code: str
    statement: str
    supporting_evidence_ids: tuple[str, ...] = ()
    counter_evidence_ids: tuple[str, ...] = ()
    missing_fact_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestionCandidate:
    fact_key: str
    question: str
    decision_impact: str
    evidence_request: str | None = None


@dataclass(frozen=True)
class SessionSnapshot:
    stage: Stage
    facts: Mapping[str, FactRecord | Any]
    evidence: Mapping[str, EvidenceRecord] = field(default_factory=dict)
    hypotheses: tuple[Hypothesis, ...] = ()
    available_tools: frozenset[ToolName] = field(default_factory=frozenset)
    tool_results: Mapping[ToolName, ToolResult | Mapping[str, Any]] = field(default_factory=dict)
    user_id: str | None = None
    store_id: str | None = None
    has_private_knowledge: bool = False

    def fact(self, key: str) -> FactRecord | None:
        if key not in self.facts:
            return None
        return FactRecord.from_value(key, self.facts[key])

    def value(self, key: str, default: Any = None) -> Any:
        record = self.fact(key)
        return default if record is None else record.value

    def result(self, tool: ToolName) -> ToolResult | None:
        if tool not in self.tool_results:
            return None
        return ToolResult.from_value(self.tool_results[tool])

    @property
    def known_evidence_ids(self) -> frozenset[str]:
        ids = set(self.evidence)
        for record in self.facts.values():
            if isinstance(record, FactRecord):
                ids.update(record.evidence_ids)
        for value in self.tool_results.values():
            ids.update(ToolResult.from_value(value).evidence_ids)
        return frozenset(ids)


@dataclass(frozen=True)
class SkillDirective:
    action: NextAction
    message: str
    missing_facts: tuple[str, ...] = ()
    question_candidates: tuple[QuestionCandidate, ...] = ()
    tool_name: ToolName | None = None
    tool_arguments: Mapping[str, Any] = field(default_factory=dict)
    allowed_conclusions: tuple[Conclusion, ...] = ()
    warning: str | None = None
    unavailable_tools: tuple[ToolName, ...] = ()
    rationale_codes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["action"] = self.action.value
        value["tool_name"] = self.tool_name.value if self.tool_name else None
        value["allowed_conclusions"] = [item.value for item in self.allowed_conclusions]
        value["unavailable_tools"] = [item.value for item in self.unavailable_tools]
        return value


@dataclass(frozen=True)
class Judgment:
    conclusion: Conclusion
    confidence: float
    decisive_evidence_ids: tuple[str, ...]
    counter_evidence_ids: tuple[str, ...]
    critical_gap: str | None
    first_action: str
    verification_condition: str
    stop_condition: str
    assumptions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")


def validate_judgment(
    judgment: Judgment,
    snapshot: SessionSnapshot,
    *,
    allowed_conclusions: Sequence[Conclusion] | None = None,
) -> tuple[str, ...]:
    """Return validation errors; never silently repair a model judgment."""

    errors: list[str] = []
    if allowed_conclusions is not None and judgment.conclusion not in allowed_conclusions:
        errors.append(f"conclusion not allowed by directive: {judgment.conclusion.value}")
    known_ids = snapshot.known_evidence_ids
    cited_ids: Sequence[str] = judgment.decisive_evidence_ids + judgment.counter_evidence_ids
    unknown = sorted(set(cited_ids) - known_ids)
    if unknown:
        errors.append(f"unknown evidence IDs: {', '.join(unknown)}")
    overlap = sorted(
        set(judgment.decisive_evidence_ids).intersection(judgment.counter_evidence_ids)
    )
    if overlap:
        errors.append(f"evidence cannot be both decisive and counterevidence: {', '.join(overlap)}")
    if judgment.conclusion != Conclusion.INSUFFICIENT_EVIDENCE and not judgment.decisive_evidence_ids:
        errors.append("a substantive conclusion requires decisive evidence")
    non_inference_ids: set[str] = {
        evidence_id
        for evidence_id, record in snapshot.evidence.items()
        if record.kind != EvidenceKind.INFERENCE
    }
    conflicted_ids: set[str] = set()
    for value in snapshot.facts.values():
        if not isinstance(value, FactRecord):
            continue
        if value.kind != EvidenceKind.INFERENCE:
            non_inference_ids.update(value.evidence_ids)
        if value.verification == VerificationStatus.CONFLICTED:
            conflicted_ids.update(value.evidence_ids)
    for value in snapshot.tool_results.values():
        non_inference_ids.update(ToolResult.from_value(value).evidence_ids)
    if (
        judgment.conclusion != Conclusion.INSUFFICIENT_EVIDENCE
        and judgment.decisive_evidence_ids
        and not set(judgment.decisive_evidence_ids).intersection(non_inference_ids)
    ):
        errors.append("a substantive conclusion requires at least one non-inference evidence item")
    decisive_conflicts = sorted(set(judgment.decisive_evidence_ids).intersection(conflicted_ids))
    if decisive_conflicts:
        errors.append(
            f"conflicted evidence cannot be decisive: {', '.join(decisive_conflicts)}"
        )
    if not judgment.first_action.strip():
        errors.append("first_action is required")
    if not judgment.verification_condition.strip():
        errors.append("verification_condition is required")
    if not judgment.stop_condition.strip():
        errors.append("stop_condition is required")
    return tuple(errors)


