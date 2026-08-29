from __future__ import annotations

from dataclasses import asdict
from typing import Any, Callable, Mapping, Sequence

from .contracts import ToolResult, ToolStatus
from .retrieval import SearchHit


class CallableEvidenceTool:
    """Normalize an injected external API into the shared evidence contract."""

    def __init__(
        self,
        call: Callable[[Mapping[str, Any]], Mapping[str, Any]],
        *,
        source: str,
        required_arguments: Sequence[str] = (),
    ) -> None:
        self.call = call
        self.source = source
        self.required_arguments = tuple(required_arguments)

    def run(self, arguments: Mapping[str, Any]) -> ToolResult:
        missing = [
            key
            for key in self.required_arguments
            if key not in arguments
            or arguments[key] is None
            or (isinstance(arguments[key], str) and not arguments[key].strip())
        ]
        if missing:
            return ToolResult(
                status=ToolStatus.INVALID_INPUT,
                source=self.source,
                error_code=f"missing:{','.join(missing)}",
            )
        try:
            value = self.call(arguments)
        except (OSError, TimeoutError, ConnectionError) as exc:
            return ToolResult(
                status=ToolStatus.UNAVAILABLE,
                source=self.source,
                error_code=type(exc).__name__,
            )
        if not isinstance(value, Mapping):
            return ToolResult(
                status=ToolStatus.INVALID_RESULT,
                source=self.source,
                error_code="tool_response_must_be_mapping",
            )
        result = ToolResult.from_value({**value, "source": value.get("source") or self.source})
        if result.status == ToolStatus.OK and not result.has_usable_evidence:
            return ToolResult(
                status=ToolStatus.INVALID_RESULT,
                source=result.source or self.source,
                error_code="ok_result_requires_source_and_evidence_ids",
            )
        return result


def retrieval_hits_to_result(hits: Sequence[SearchHit], *, source: str) -> ToolResult:
    """Convert scoped retrieval hits into the shared tool evidence contract."""

    if not source.strip():
        raise ValueError("source is required")
    if not hits:
        return ToolResult(status=ToolStatus.NO_HIT, source=source, data={"hits": []})
    return ToolResult(
        status=ToolStatus.OK,
        evidence_ids=tuple(hit.evidence_id for hit in hits),
        data={"hits": [asdict(hit) for hit in hits]},
        source=source,
    )


