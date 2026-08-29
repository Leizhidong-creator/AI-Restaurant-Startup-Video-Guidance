from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .contracts import ToolResult, ToolStatus


@dataclass(frozen=True)
class CaptureRequirement:
    code: str
    instruction: str
    purpose: str


SITE_CAPTURE_REQUIREMENTS: tuple[CaptureRequirement, ...] = (
    CaptureRequirement("front", "从道路对面稳定拍摄门头正面至少 5 秒", "核验可见性与产品表达"),
    CaptureRequirement("left", "站在门口向左缓慢拍摄至主要来客方向", "核验左侧动线与遮挡"),
    CaptureRequirement("right", "站在门口向右缓慢拍摄至主要来客方向", "核验右侧动线与邻店"),
    CaptureRequirement("opposite", "拍摄道路对面、过街方式和隔离设施", "核验对面客流能否到达"),
    CaptureRequirement("entrance", "从主要入口按真实步行路线走到铺位", "核验入口距离与转弯损耗"),
    CaptureRequirement("parking", "拍摄停车、骑行和外卖取餐动线", "核验到店便利性"),
)


def capture_checklist() -> tuple[dict[str, str], ...]:
    return tuple(
        {"code": item.code, "instruction": item.instruction, "purpose": item.purpose}
        for item in SITE_CAPTURE_REQUIREMENTS
    )


def build_visual_prompt(*, stage: str, category: str, target_period: str) -> str:
    schema = {
        "coverage_codes": [item.code for item in SITE_CAPTURE_REQUIREMENTS],
        "observations": [
            {
                "observation": "only directly visible fact",
                "frame_locator": "timestamp or frame id",
                "confidence": "0..1",
            }
        ],
        "inferences": [
            {
                "inference": "interpretation separated from observation",
                "supporting_frame_locators": ["timestamp or frame id"],
                "confidence": "0..1",
            }
        ],
        "missing_captures": ["coverage code"],
    }
    return (
        "Analyze storefront evidence, not business success. Do not estimate unobserved footfall, "
        "revenue or customer intent. Separate visible observations from inferences. "
        f"Stage={stage}; category={category}; target_period={target_period}. "
        f"Return JSON matching: {json.dumps(schema, ensure_ascii=False)}"
    )


class CallableVisionAnalyzer:
    """Validate structured output from an injected multimodal model callable."""

    def __init__(
        self,
        model_call: Callable[[Sequence[str], str], Mapping[str, Any]],
        *,
        model_name: str,
    ) -> None:
        self.model_call = model_call
        self.model_name = model_name

    def analyze(
        self,
        media_refs: Sequence[str],
        *,
        stage: str,
        category: str,
        target_period: str,
    ) -> ToolResult:
        if not media_refs:
            return ToolResult(
                status=ToolStatus.INVALID_INPUT,
                source=f"visual-analysis:{self.model_name}",
                error_code="media_refs_required",
            )
        prompt = build_visual_prompt(
            stage=stage,
            category=category,
            target_period=target_period,
        )
        value = self.model_call(media_refs, prompt)
        if not isinstance(value, Mapping):
            return ToolResult(
                status=ToolStatus.INVALID_RESULT,
                source=f"visual-analysis:{self.model_name}",
                error_code="model_response_must_be_mapping",
            )
        observations = value.get("observations", [])
        inferences = value.get("inferences", [])
        missing_captures = value.get("missing_captures", [])
        coverage_codes = value.get("coverage_codes", [])
        if not all(
            isinstance(item, list)
            for item in (observations, inferences, missing_captures, coverage_codes)
        ):
            return ToolResult(
                status=ToolStatus.INVALID_RESULT,
                source=f"visual-analysis:{self.model_name}",
                error_code="visual_result_collections_must_be_lists",
            )
        def valid_confidence(item: Mapping[str, Any]) -> bool:
            if "confidence" not in item:
                return True
            value = item["confidence"]
            return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 1

        invalid_observation = any(
            not isinstance(item, Mapping)
            or not str(item.get("observation", "")).strip()
            or not str(item.get("frame_locator", "")).strip()
            or not valid_confidence(item)
            for item in observations
        )
        if invalid_observation:
            return ToolResult(
                status=ToolStatus.INVALID_RESULT,
                source=f"visual-analysis:{self.model_name}",
                error_code="every_observation_requires_text_and_frame_locator",
            )
        invalid_inference = any(
            not isinstance(item, Mapping)
            or not str(item.get("inference", "")).strip()
            or not isinstance(item.get("supporting_frame_locators"), list)
            or not item.get("supporting_frame_locators")
            or not valid_confidence(item)
            for item in inferences
        )
        if invalid_inference:
            return ToolResult(
                status=ToolStatus.INVALID_RESULT,
                source=f"visual-analysis:{self.model_name}",
                error_code="every_inference_requires_text_and_supporting_frames",
            )
        canonical = json.dumps(
            {
                "model": self.model_name,
                "media_refs": list(media_refs),
                "result": value,
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
        evidence_id = f"visual:storefront:{digest}:1.0"
        status = ToolStatus.NO_HIT if not observations else ToolStatus.OK
        return ToolResult(
            status=status,
            evidence_ids=(evidence_id,) if status == ToolStatus.OK else (),
            data={
                "coverage_codes": list(coverage_codes),
                "observations": observations,
                "inferences": inferences,
                "missing_captures": list(missing_captures),
                "boundary": "Visual observations do not prove footfall, demand or revenue.",
            },
            source=f"visual-analysis:{self.model_name}",
        )


