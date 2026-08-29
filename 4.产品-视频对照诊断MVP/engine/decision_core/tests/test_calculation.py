from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from restaurant_handoff import ToolStatus, calculate_business_metrics, simulate_scenario


class CalculationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.facts = {
            "average_daily_revenue": 600,
            "operating_days_per_month": 30,
            "contribution_margin_rate": 0.6,
            "monthly_rent": 6000,
            "monthly_labor_cost": 9000,
            "monthly_other_fixed_cost": 5000,
            "remaining_cash": 50000,
        }

    def test_break_even_and_runway_are_deterministic(self) -> None:
        result = calculate_business_metrics(self.facts)
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertAlmostEqual(result.data["break_even_daily_revenue"], 1111.11, places=2)
        self.assertEqual(result.data["monthly_operating_profit_before_tax"], -9200.0)
        self.assertAlmostEqual(result.data["cash_runway_months_at_current_model"], 5.43, places=2)
        self.assertTrue(result.evidence_ids[0].startswith("calc:business:"))

    def test_invalid_margin_returns_invalid_input_not_guess(self) -> None:
        result = calculate_business_metrics({**self.facts, "contribution_margin_rate": 1.2})
        self.assertEqual(result.status, ToolStatus.INVALID_INPUT)
        self.assertFalse(result.evidence_ids)

    def test_counterfactual_states_demand_boundary(self) -> None:
        result = simulate_scenario(self.facts, {"monthly_labor_cost": 5000})
        self.assertEqual(result.status, ToolStatus.OK)
        self.assertIn("not predicted", result.data["boundary"])
        self.assertEqual(result.data["counterfactual_changes"], {"monthly_labor_cost": 5000})


if __name__ == "__main__":
    unittest.main()


