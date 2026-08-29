from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from yongge_online.db.models import ExperienceLevel, StoreStage


class UserCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    phone: str | None = Field(default=None, max_length=32)
    experience_level: ExperienceLevel = ExperienceLevel.NOVICE


class UserRead(UserCreate):
    model_config = ConfigDict(from_attributes=True)

    id: str
    created_at: datetime
    updated_at: datetime


class StoreFields(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    stage: StoreStage
    address: str | None = None
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    area_sqm: Decimal | None = Field(default=None, ge=0)
    seats: int | None = Field(default=None, ge=0)
    initial_investment: Decimal | None = Field(default=None, ge=0)
    monthly_revenue: Decimal | None = Field(default=None, ge=0)
    monthly_rent: Decimal | None = Field(default=None, ge=0)
    monthly_labor_cost: Decimal | None = Field(default=None, ge=0)
    monthly_other_fixed_cost: Decimal | None = Field(default=None, ge=0)
    ingredient_cost_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    operating_days_per_month: int = Field(default=30, ge=1, le=31)


class StoreCreate(StoreFields):
    pass


class StoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    brand: str | None = Field(default=None, max_length=120)
    category: str | None = Field(default=None, min_length=1, max_length=80)
    stage: StoreStage | None = None
    address: str | None = None
    longitude: Decimal | None = Field(default=None, ge=-180, le=180)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90)
    area_sqm: Decimal | None = Field(default=None, ge=0)
    seats: int | None = Field(default=None, ge=0)
    initial_investment: Decimal | None = Field(default=None, ge=0)
    monthly_revenue: Decimal | None = Field(default=None, ge=0)
    monthly_rent: Decimal | None = Field(default=None, ge=0)
    monthly_labor_cost: Decimal | None = Field(default=None, ge=0)
    monthly_other_fixed_cost: Decimal | None = Field(default=None, ge=0)
    ingredient_cost_rate: Decimal | None = Field(default=None, ge=0, lt=1)
    operating_days_per_month: int | None = Field(default=None, ge=1, le=31)


class StoreRead(StoreFields):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    created_at: datetime
    updated_at: datetime


