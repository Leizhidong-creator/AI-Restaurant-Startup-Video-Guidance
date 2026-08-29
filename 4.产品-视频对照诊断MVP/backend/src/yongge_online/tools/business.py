import ast
import operator
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Callable, Mapping

from yongge_online.tools.schemas import BusinessMetrics, StoreSnapshot

MONEY = Decimal("0.01")
RATE = Decimal("0.0001")

_BINARY_OPERATORS: dict[type[ast.operator], Callable[[Decimal, Decimal], Decimal]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


class _CalculationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def rate(value: Decimal) -> Decimal:
    return value.quantize(RATE, rounding=ROUND_HALF_UP)


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _evaluate_expression(node: ast.AST, variables: Mapping[str, Decimal]) -> Decimal:
    if isinstance(node, ast.Expression):
        return _evaluate_expression(node.body, variables)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        value = Decimal(str(node.value))
        if not value.is_finite():
            raise _CalculationError("invalid_number", "数字必须是有限值")
        return value
    if isinstance(node, ast.Name):
        if node.id not in variables:
            raise _CalculationError("unknown_variable", f"缺少变量：{node.id}")
        return variables[node.id]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _evaluate_expression(node.operand, variables)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY_OPERATORS:
        left = _evaluate_expression(node.left, variables)
        right = _evaluate_expression(node.right, variables)
        if isinstance(node.op, ast.Div) and right == 0:
            raise _CalculationError("division_by_zero", "除数不能为 0")
        return _BINARY_OPERATORS[type(node.op)](left, right)
    raise _CalculationError(
        "unsupported_expression",
        "只支持数字、变量、括号和加减乘除",
    )


def calculate_expression(
    *,
    expression: str,
    variables: Mapping[str, Decimal] | None = None,
    unit: str | None = None,
) -> dict[str, object]:
    """Safely execute deterministic arithmetic without eval or business judgment."""

    normalized_variables = {
        name: value if isinstance(value, Decimal) else Decimal(str(value))
        for name, value in (variables or {}).items()
    }
    try:
        tree = ast.parse(expression, mode="eval")
        if len(list(ast.walk(tree))) > 64:
            raise _CalculationError("expression_too_complex", "计算式过于复杂")
        with localcontext() as context:
            context.prec = 28
            result = _evaluate_expression(tree, normalized_variables)
        if not result.is_finite():
            raise _CalculationError("invalid_result", "计算结果不是有限值")
    except SyntaxError:
        error = _CalculationError("invalid_expression", "计算式格式不正确")
    except (InvalidOperation, ValueError) as exc:
        error = (
            exc
            if isinstance(exc, _CalculationError)
            else _CalculationError("invalid_number", "数字格式不正确")
        )
    else:
        return {
            "available": True,
            "expression": expression,
            "variables": {
                name: _decimal_text(value)
                for name, value in normalized_variables.items()
            },
            "result": _decimal_text(result),
            "unit": unit,
        }

    return {
        "available": False,
        "expression": expression,
        "variables": {
            name: _decimal_text(value) for name, value in normalized_variables.items()
        },
        "result": None,
        "unit": unit,
        "error_code": error.code,
        "message": str(error),
    }


def calculate_business_metrics(store: StoreSnapshot) -> BusinessMetrics:
    required = (
        "monthly_rent",
        "monthly_labor_cost",
        "monthly_other_fixed_cost",
        "ingredient_cost_rate",
    )
    missing = [field for field in required if getattr(store, field) is None]
    if missing:
        return BusinessMetrics(available=False, missing_fields=missing)

    rent = store.monthly_rent
    labor = store.monthly_labor_cost
    other = store.monthly_other_fixed_cost
    cost_rate = store.ingredient_cost_rate
    assert rent is not None
    assert labor is not None
    assert other is not None
    assert cost_rate is not None

    contribution_rate = Decimal("1") - cost_rate
    if contribution_rate <= 0:
        return BusinessMetrics(
            available=False,
            missing_fields=["ingredient_cost_rate_must_be_below_one"],
        )

    fixed_cost = rent + labor + other
    break_even = fixed_cost / contribution_rate
    operating_days = Decimal(store.operating_days_per_month)
    revenue = store.monthly_revenue
    if revenue is None:
        return BusinessMetrics(
            available=True,
            missing_fields=["monthly_revenue"],
            monthly_fixed_cost=money(fixed_cost),
            contribution_margin_rate=rate(contribution_rate),
            break_even_monthly_revenue=money(break_even),
            break_even_daily_revenue=money(break_even / operating_days),
        )

    variable_cost = revenue * cost_rate
    gross_profit = revenue * contribution_rate
    profit = gross_profit - fixed_cost
    average_daily = revenue / operating_days
    safety_margin = (revenue - break_even) / revenue if revenue > 0 else None

    return BusinessMetrics(
        available=True,
        monthly_revenue=money(revenue),
        monthly_variable_cost=money(variable_cost),
        monthly_gross_profit=money(gross_profit),
        monthly_fixed_cost=money(fixed_cost),
        monthly_profit=money(profit),
        contribution_margin_rate=rate(contribution_rate),
        break_even_monthly_revenue=money(break_even),
        break_even_daily_revenue=money(break_even / operating_days),
        average_daily_revenue=money(average_daily),
        safety_margin_rate=rate(safety_margin) if safety_margin is not None else None,
    )


