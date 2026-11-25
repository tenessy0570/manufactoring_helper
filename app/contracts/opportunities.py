"""Shared opportunity settings stored in profiles and accepted by calculation endpoints."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domains.market.enums import OrderType
from app.domains.market.models import HubId


class LiquidityFilters(BaseModel):
    hub_id: HubId = "jita"
    days: int = Field(default=30, ge=1, le=365)
    type_ids: list[int] | None = Field(default=None, max_length=1000)
    exclude_type_ids: list[int] | None = Field(default=None, max_length=1000)
    search: str | None = Field(default=None, min_length=1, max_length=200)
    categories: list[str] | None = Field(default=None, max_length=100)
    meta_group_ids: list[int] | None = Field(default=None, max_length=100)
    is_rig: bool | None = None
    min_daily_isk_volume: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_daily_isk_volume: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    min_daily_units: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_daily_units: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    has_history: bool | None = None
    fresh_only: bool = False
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "LiquidityFilters":
        for low, high in (
            (self.min_daily_units, self.max_daily_units),
            (self.min_daily_isk_volume, self.max_daily_isk_volume),
        ):
            if low is not None and high is not None and low > high:
                raise ValueError("Minimum must not exceed maximum")
        return self


class OpportunitySettings(LiquidityFilters):
    @model_validator(mode="before")
    @classmethod
    def discard_legacy_skill_settings(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            if value.get("invention_slots") in (None, ""):
                value["invention_slots"] = 1
            if value.get("production_lines") in (None, ""):
                value["production_lines"] = 1
            if value.get("buy_demand_tolerance_pct") in (None, ""):
                value["buy_demand_tolerance_pct"] = 5
            for side in ("buy", "sell"):
                value.setdefault(f"{side}_broker_fee", value.get("broker_fee", 0))
            for name in (
                "buy_broker_fee",
                "sell_broker_fee",
                "sales_tax",
                "facility_tax",
                "system_cost_index",
            ):
                if value.get(name) in (None, ""):
                    value[name] = 0
            return {
                key: item
                for key, item in value.items()
                if key not in ("invention_science_level", "invention_encryption_level")
            }
        return value

    buy_demand_tolerance_pct: Decimal = Field(default=Decimal(5), ge=0, le=100, allow_inf_nan=False)
    include_copying_time: bool = False
    include_invention_time: bool = False
    invention_slots: int = Field(default=1, ge=1, le=1000)
    production_lines: int = Field(default=1, ge=1, le=1000)
    include_invention_cost: bool = False
    material_order_type: OrderType = "sell"
    product_order_type: OrderType = "sell"
    material_hub_id: HubId | None = None
    sales_tax: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    broker_fee: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    buy_broker_fee: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    sell_broker_fee: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    facility_tax: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    system_cost_index: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    job_cost_per_run: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    min_profit: Decimal | None = Field(default=None, allow_inf_nan=False)
    max_profit: Decimal | None = Field(default=None, allow_inf_nan=False)
    min_margin: Decimal | None = Field(default=None, allow_inf_nan=False)
    max_margin: Decimal | None = Field(default=None, allow_inf_nan=False)
    min_profit_per_day: Decimal | None = Field(default=None, allow_inf_nan=False)
    min_product_orders: int | None = Field(default=None, ge=0)
    min_orders_at_price: int | None = Field(default=None, ge=0)
    min_product_volume: int | None = Field(default=None, ge=0)
    require_full_run_demand: bool = False
    exclude_fragile_buy_demand: bool = False
    rank_by: Literal["profit_per_day", "margin", "profit", "demand_profit"] = "profit_per_day"

    @model_validator(mode="after")
    def validate_profit_ranges(self) -> "OpportunitySettings":
        for low, high in ((self.min_profit, self.max_profit), (self.min_margin, self.max_margin)):
            if low is not None and high is not None and low > high:
                raise ValueError("Minimum must not exceed maximum")
        if self.sales_tax + self.sell_broker_fee > 100:
            raise ValueError("Combined sales tax and broker fee must not exceed 100%")
        return self
