from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Awaitable, Callable, Mapping

from .contracts import (
    EvidenceKind,
    FactRecord,
    NextAction,
    SessionSnapshot,
    SkillDirective,
    ToolName,
    ToolResult,
    ToolStatus,
    VerificationStatus,
)
from .skill import RestaurantSkillProvider


ToolCallable = Callable[[Mapping[str, object]], ToolResult]
AsyncToolCallable = Callable[[Mapping[str, object]], Awaitable[ToolResult]]


class RuntimeLoopError(RuntimeError):
    pass


class ToolRegistry:
    """Bind normalized tool callables without coupling the Skill to a backend."""

    def __init__(self, tools: Mapping[ToolName, ToolCallable] | None = None) -> None:
        self._tools: dict[ToolName, ToolCallable] = dict(tools or {})

    def register(self, name: ToolName, call: ToolCallable) -> None:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name.value}")
        self._tools[name] = call

    @property
    def available_tools(self) -> frozenset[ToolName]:
        return frozenset(self._tools)

    def run(self, name: ToolName, arguments: Mapping[str, object]) -> ToolResult:
        if name not in self._tools:
            raise KeyError(f"tool not registered: {name.value}")
        result = self._tools[name](arguments)
        if not isinstance(result, ToolResult):
            raise TypeError(f"tool {name.value} must return ToolResult")
        return result


class AsyncToolRegistry:
    """Async equivalent for FastAPI, realtime and network-bound backends."""

    def __init__(self, tools: Mapping[ToolName, AsyncToolCallable] | None = None) -> None:
        self._tools: dict[ToolName, AsyncToolCallable] = dict(tools or {})

    def register(self, name: ToolName, call: AsyncToolCallable) -> None:
        if name in self._tools:
            raise ValueError(f"tool already registered: {name.value}")
        self._tools[name] = call

    @property
    def available_tools(self) -> frozenset[ToolName]:
        return frozenset(self._tools)

    async def run(self, name: ToolName, arguments: Mapping[str, object]) -> ToolResult:
        if name not in self._tools:
            raise KeyError(f"tool not registered: {name.value}")
        result = await self._tools[name](arguments)
        if not isinstance(result, ToolResult):
            raise TypeError(f"tool {name.value} must return ToolResult")
        return result


@dataclass(frozen=True)
class TraceEvent:
    sequence: int
    directive: SkillDirective
    tool_result: ToolResult | None = None

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "sequence": self.sequence,
            "directive": self.directive.to_dict(),
        }
        if self.tool_result is not None:
            value["tool_result"] = self.tool_result.to_dict()
        return value


@dataclass(frozen=True)
class RuntimeResult:
    snapshot: SessionSnapshot
    directive: SkillDirective
    trace: tuple[TraceEvent, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "directive": self.directive.to_dict(),
            "tool_results": {
                name.value: self.snapshot.result(name).to_dict()
                for name in self.snapshot.tool_results
                if self.snapshot.result(name) is not None
            },
            "trace": [event.to_dict() for event in self.trace],
        }


class DecisionRuntime:
    """Execute consecutive tool directives and stop at the next human/model boundary."""

    def __init__(
        self,
        provider: RestaurantSkillProvider,
        registry: ToolRegistry,
        *,
        max_tool_steps: int = 12,
    ) -> None:
        if max_tool_steps < 1:
            raise ValueError("max_tool_steps must be >= 1")
        self.provider = provider
        self.registry = registry
        self.max_tool_steps = max_tool_steps

    def advance(self, snapshot: SessionSnapshot) -> RuntimeResult:
        current = replace(snapshot, available_tools=self.registry.available_tools)
        trace: list[TraceEvent] = []
        for sequence in range(1, self.max_tool_steps + 2):
            directive = self.provider.next_directive(current)
            if directive.action != NextAction.CALL_TOOL:
                trace.append(TraceEvent(sequence=sequence, directive=directive))
                return RuntimeResult(
                    snapshot=current,
                    directive=directive,
                    trace=tuple(trace),
                )
            if sequence > self.max_tool_steps:
                raise RuntimeLoopError(
                    f"tool loop exceeded {self.max_tool_steps} steps without reaching a boundary"
                )
            if directive.tool_name is None:
                raise RuntimeLoopError("call_tool directive has no tool_name")
            result = self.registry.run(directive.tool_name, directive.tool_arguments)
            trace.append(
                TraceEvent(sequence=sequence, directive=directive, tool_result=result)
            )
            tool_results = dict(current.tool_results)
            tool_results[directive.tool_name] = result
            current = replace(current, tool_results=tool_results)
            current = self._hydrate_store_profile(current, directive.tool_name, result)
        raise RuntimeLoopError("unreachable runtime loop state")

    @staticmethod
    def _hydrate_store_profile(
        snapshot: SessionSnapshot,
        tool_name: ToolName,
        result: ToolResult,
    ) -> SessionSnapshot:
        if tool_name != ToolName.STORE_PROFILE or result.status != ToolStatus.OK:
            return snapshot
        raw_facts = result.data.get("facts")
        if not isinstance(raw_facts, Mapping) or not result.evidence_ids:
            return snapshot
        facts = dict(snapshot.facts)
        for key, value in raw_facts.items():
            if not isinstance(key, str) or not key.strip() or key in facts or value is None:
                continue
            facts[key] = FactRecord(
                key=key,
                value=value,
                kind=EvidenceKind.TOOL,
                verification=VerificationStatus.TOOL_VERIFIED,
                evidence_ids=result.evidence_ids,
                source=result.source,
            )
        return replace(snapshot, facts=facts)


class AsyncDecisionRuntime:
    """Execute async tool directives without blocking a realtime server event loop."""

    def __init__(
        self,
        provider: RestaurantSkillProvider,
        registry: AsyncToolRegistry,
        *,
        max_tool_steps: int = 12,
    ) -> None:
        if max_tool_steps < 1:
            raise ValueError("max_tool_steps must be >= 1")
        self.provider = provider
        self.registry = registry
        self.max_tool_steps = max_tool_steps

    async def advance(self, snapshot: SessionSnapshot) -> RuntimeResult:
        current = replace(snapshot, available_tools=self.registry.available_tools)
        trace: list[TraceEvent] = []
        for sequence in range(1, self.max_tool_steps + 2):
            directive = self.provider.next_directive(current)
            if directive.action != NextAction.CALL_TOOL:
                trace.append(TraceEvent(sequence=sequence, directive=directive))
                return RuntimeResult(
                    snapshot=current,
                    directive=directive,
                    trace=tuple(trace),
                )
            if sequence > self.max_tool_steps:
                raise RuntimeLoopError(
                    f"tool loop exceeded {self.max_tool_steps} steps without reaching a boundary"
                )
            if directive.tool_name is None:
                raise RuntimeLoopError("call_tool directive has no tool_name")
            result = await self.registry.run(
                directive.tool_name, directive.tool_arguments
            )
            trace.append(
                TraceEvent(sequence=sequence, directive=directive, tool_result=result)
            )
            tool_results = dict(current.tool_results)
            tool_results[directive.tool_name] = result
            current = replace(current, tool_results=tool_results)
            current = DecisionRuntime._hydrate_store_profile(
                current, directive.tool_name, result
            )
        raise RuntimeLoopError("unreachable runtime loop state")


