from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import SessionSnapshot, Stage, ToolName, RestaurantSkillProvider


def main() -> int:
    provider = RestaurantSkillProvider()
    failures: list[str] = []
    case_count = 0
    path = ROOT / "evals" / "golden_scenarios.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        case_count += 1
        case = json.loads(line)
        tool_results = {
            ToolName(key): value for key, value in case.get("tool_results", {}).items()
        }
        snapshot = SessionSnapshot(
            stage=Stage(case["stage"]),
            facts=case["facts"],
            available_tools=frozenset(ToolName(item) for item in case.get("available_tools", [])),
            tool_results=tool_results,
        )
        directive = provider.next_directive(snapshot)
        expected = case["expect"]
        actual = directive.to_dict()
        if actual["action"] != expected["action"]:
            failures.append(f"{case['case_id']}: action={actual['action']}")
        if expected.get("tool_name") and actual["tool_name"] != expected["tool_name"]:
            failures.append(
                f"{case['case_id']}: tool={actual['tool_name']} expected={expected['tool_name']}"
            )
        first_missing = expected.get("first_missing_fact")
        if first_missing and (not directive.missing_facts or directive.missing_facts[0] != first_missing):
            failures.append(f"{case['case_id']}: first_missing={directive.missing_facts[:1]}")
        if "allowed_conclusions" in expected and actual["allowed_conclusions"] != expected["allowed_conclusions"]:
            failures.append(
                f"{case['case_id']}: allowed={actual['allowed_conclusions']} expected={expected['allowed_conclusions']}"
            )
        warning_contains = expected.get("warning_contains")
        if warning_contains is None and directive.warning is not None:
            failures.append(f"{case['case_id']}: unexpected warning={directive.warning}")
        if warning_contains and warning_contains not in (directive.warning or ""):
            failures.append(f"{case['case_id']}: missing warning token={warning_contains}")

    if failures:
        print("\n".join(failures))
        return 1
    print(f"{case_count} deterministic safety/evidence scenarios passed")
    print("Semantic question quality and final business judgment still require model + human evaluation.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


