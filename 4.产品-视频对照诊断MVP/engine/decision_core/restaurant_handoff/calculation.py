from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .contracts import ToolResult, ToolStatus


CALCULATION_VERSION = "business-calculation:2.0"


class CalculationInputError(ValueError):
    pass


def _number(facts: Mapping[str, Any], key: str, *, minimum: float = 0) -> float:
    if key not in facts:
        raise CalculationInputError(f"missing required input: {key}")
    value = facts[key]
    if isinstance(value, bool):
        raise CalculationInputError(f"{key} must be a number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CalculationInputError(f"{key} must be a number") from exc
    if number < minimum:
        raise CalculationInputError(f"{key} must be >= {minimum}")
    return number


def calculate_business_metrics(facts: Mapping[str, Any]) -> ToolResult:
    """Calculate auditable operating metrics without making a business judgment."""

    try:
        daily_revenue = _number(
            facts,
            "average_daily_revenue"
            if "average_daily_revenue" in facts
            else "expected_daily_revenue",
        )
        operating_days = _number(facts, "operating_days_per_month", minimum=1)
        if operating_days > 31:
            raise CalculationInputError("operating_days_per_month must be <= 31")
        contribution_margin_rate = _number(facts, "contribution_margin_rate")
        if not 0 < contribution_margin_rate <= 1:
            raise CalculationInputError("contribution_margin_rate must be in (0, 1]")
        monthly_rent = _number(facts, "monthly_rent")
        monthly_labor = _number(facts, "monthly_labor_cost")
        monthly_other = _number(facts, "monthly_other_fixed_cost")
    except CalculationInputError as exc:
        return ToolResult(
            status=ToolStatus.INVALID_INPUT,
            source=CALCULATION_VERSION,
            error_code=str(exc),
        )

    monthly_revenue = daily_revenue * operating_days
    monthly_contribution = monthly_revenue * contribution_margin_rate
    monthly_fixed_cost = monthly_rent + monthly_labor + monthly_other
    monthly_operating_profit = monthly_contribution - monthly_fixed_cost
    break_even_monthly_revenue = monthly_fixed_cost / contribution_margin_rate
    break_even_daily_revenue = break_even_monthly_revenue / operating_days
    revenue_gap_to_break_even = daily_revenue - break_even_daily_revenue

    data: dict[str, Any] = {
        "currency": "CNY",
        "monthly_revenue": round(monthly_revenue, 2),
        "monthly_contribution": round(monthly_contribution, 2),
        "monthly_fixed_cost": round(monthly_fixed_cost, 2),
        "monthly_operating_profit_before_tax": round(monthly_operating_profit, 2),
        "break_even_monthly_revenue": round(break_even_monthly_revenue, 2),
        "break_even_daily_revenue": round(break_even_daily_revenue, 2),
        "daily_revenue_gap_to_break_even": round(revenue_gap_to_break_even, 2),
        "assumptions": {
            "operating_days_per_month": operating_days,
            "contribution_margin_rate": contribution_margin_rate,
            "tax_and_depreciation_included": False,
        },
    }
    if "remaining_cash" in facts and monthly_operating_profit < 0:
        try:
            remaining_cash = _number(facts, "remaining_cash")
            data["cash_runway_months_at_current_model"] = round(
                remaining_cash / abs(monthly_operating_profit), 2
            )
        except CalculationInputError:
            pass

    canonical = json.dumps(
        {"version": CALCULATION_VERSION, "inputs": dict(sorted(facts.items()))},
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    evidence_id = f"calc:business:{digest}:{CALCULATION_VERSION.rsplit(':', 1)[-1]}"
    return ToolResult(
        status=ToolStatus.OK,
        evidence_ids=(evidence_id,),
        data=data,
        source=CALCULATION_VERSION,
    )


def simulate_scenario(
    baseline_facts: Mapping[str, Any], changes: Mapping[str, Any]
) -> ToolResult:
    """Recalculate a user-defined counterfactual; never predicts demand changes."""

    merged = {**baseline_facts, **changes}
    result = calculate_business_metrics(merged)
    if result.status != ToolStatus.OK:
        return result
    return ToolResult(
        status=result.status,
        evidence_ids=result.evidence_ids,
        data={
            **result.data,
            "counterfactual_changes": dict(changes),
            "boundary": "Only deterministic financial effects were recalculated; demand and execution were not predicted.",
        },
        source=f"{CALCULATION_VERSION}:counterfactual",
    )


