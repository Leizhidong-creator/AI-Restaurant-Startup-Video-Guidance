from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class StoreSnapshot(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str | None = None
    name: str
    brand: str | None = None
    category: str
    stage: str
    address: str | None = None
    longitude: Decimal | None = None
    latitude: Decimal | None = None
    area_sqm: Decimal | None = None
    seats: int | None = None
    initial_investment: Decimal | None = None
    monthly_revenue: Decimal | None = None
    monthly_rent: Decimal | None = None
    monthly_labor_cost: Decimal | None = None
    monthly_other_fixed_cost: Decimal | None = None
    ingredient_cost_rate: Decimal | None = None
    operating_days_per_month: int = 30


class BusinessMetrics(BaseModel):
    available: bool
    missing_fields: list[str] = Field(default_factory=list)
    monthly_revenue: Decimal | None = None
    monthly_variable_cost: Decimal | None = None
    monthly_gross_profit: Decimal | None = None
    monthly_fixed_cost: Decimal | None = None
    monthly_profit: Decimal | None = None
    contribution_margin_rate: Decimal | None = None
    break_even_monthly_revenue: Decimal | None = None
    break_even_daily_revenue: Decimal | None = None
    average_daily_revenue: Decimal | None = None
    safety_margin_rate: Decimal | None = None


class BusinessMetricsInput(BaseModel):
    """通话中用户刚提供的数据；非空字段覆盖建档快照后再做确定性计算。"""

    model_config = ConfigDict(extra="forbid")

    monthly_revenue: Decimal | None = Field(default=None, ge=0)
    monthly_rent: Decimal | None = Field(default=None, ge=0)
    monthly_labor_cost: Decimal | None = Field(default=None, ge=0)
    monthly_other_fixed_cost: Decimal | None = Field(default=None, ge=0)
    ingredient_cost_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    operating_days_per_month: int | None = Field(default=None, ge=1, le=31)


class CalculatorInput(BaseModel):
    """通用确定性算术；模型负责说明公式与业务假设，工具只负责精确计算。"""

    model_config = ConfigDict(extra="forbid")

    expression: str = Field(min_length=1, max_length=300)
    variables: dict[str, Decimal] = Field(default_factory=dict)
    unit: str | None = Field(default=None, max_length=30)


class Competitor(BaseModel):
    name: str
    category: str | None = None
    distance_m: int | None = None
    address: str | None = None


class MapSearchResult(BaseModel):
    available: bool
    reason: str | None = None
    radius_m: int
    competitors: list[Competitor] = Field(default_factory=list)


class KnowledgeQuery(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=50)


class PlatformKnowledgeQuery(KnowledgeQuery):
    category: str | None = Field(default=None, max_length=80)
    stage: str | None = Field(default=None, max_length=40)
    region: str | None = Field(default=None, max_length=120)


class MapQuery(BaseModel):
    radius_m: int = Field(default=1000, ge=100, le=5000)


