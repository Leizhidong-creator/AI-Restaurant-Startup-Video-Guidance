from decimal import Decimal

from yongge_online.tools.business import calculate_business_metrics, calculate_expression
from yongge_online.tools.schemas import StoreSnapshot


def test_calculates_profit_break_even_and_safety_margin_with_decimal() -> None:
    snapshot = StoreSnapshot(
        id="store-1",
        name="亏损奶茶店",
        category="奶茶",
        stage="operating",
        monthly_revenue=Decimal("36000"),
        monthly_rent=Decimal("12000"),
        monthly_labor_cost=Decimal("11000"),
        monthly_other_fixed_cost=Decimal("3000"),
        ingredient_cost_rate=Decimal("0.35"),
        operating_days_per_month=30,
    )

    metrics = calculate_business_metrics(snapshot)

    assert metrics.available is True
    assert metrics.monthly_gross_profit == Decimal("23400.00")
    assert metrics.monthly_profit == Decimal("-2600.00")
    assert metrics.break_even_monthly_revenue == Decimal("40000.00")
    assert metrics.break_even_daily_revenue == Decimal("1333.33")
    assert metrics.safety_margin_rate == Decimal("-0.1111")


def test_missing_cost_rate_returns_explainable_unavailable_result() -> None:
    snapshot = StoreSnapshot(
        id="store-2",
        name="资料不全门店",
        category="快餐",
        stage="operating",
        monthly_revenue=Decimal("50000"),
        monthly_rent=Decimal("10000"),
        monthly_labor_cost=Decimal("10000"),
        monthly_other_fixed_cost=Decimal("2000"),
        ingredient_cost_rate=None,
        operating_days_per_month=30,
    )

    metrics = calculate_business_metrics(snapshot)

    assert metrics.available is False
    assert metrics.missing_fields == ["ingredient_cost_rate"]
    assert metrics.monthly_profit is None


def test_break_even_is_available_without_existing_revenue() -> None:
    snapshot = StoreSnapshot(
        id="store-3",
        name="筹备中的奶茶店",
        category="奶茶",
        stage="planning",
        monthly_rent=Decimal("10000"),
        monthly_labor_cost=Decimal("9000"),
        monthly_other_fixed_cost=Decimal("2000"),
        ingredient_cost_rate=Decimal("0.35"),
        operating_days_per_month=30,
    )

    metrics = calculate_business_metrics(snapshot)

    assert metrics.available is True
    assert metrics.missing_fields == ["monthly_revenue"]
    assert metrics.break_even_monthly_revenue == Decimal("32307.69")
    assert metrics.break_even_daily_revenue == Decimal("1076.92")
    assert metrics.monthly_profit is None


def test_calculates_general_expression_with_named_variables() -> None:
    result = calculate_expression(
        expression="(revenue - fixed_cost) / investment * 100",
        variables={
            "revenue": Decimal("50000"),
            "fixed_cost": Decimal("30000"),
            "investment": Decimal("80000"),
        },
        unit="%",
    )

    assert result == {
        "available": True,
        "expression": "(revenue - fixed_cost) / investment * 100",
        "variables": {
            "revenue": "50000",
            "fixed_cost": "30000",
            "investment": "80000",
        },
        "result": "25",
        "unit": "%",
    }


def test_general_calculator_rejects_unsafe_or_invalid_expressions() -> None:
    unsafe = calculate_expression(expression="__import__('os').getcwd()")
    division_by_zero = calculate_expression(expression="10 / 0")

    assert unsafe["available"] is False
    assert unsafe["error_code"] == "unsupported_expression"
    assert division_by_zero["available"] is False
    assert division_by_zero["error_code"] == "division_by_zero"


