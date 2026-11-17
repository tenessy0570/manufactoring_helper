from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domains.history.models import LiquidityQuery
from app.domains.market.models import HubId, MarketPrice


class Material(BaseModel):
    type_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class Recipe(BaseModel):
    type_id: int
    blueprint_id: int
    units: int = Field(gt=0)
    seconds: Decimal = Field(gt=0, allow_inf_nan=False)
    job_cost: Decimal = Field(ge=0, allow_inf_nan=False)
    estimated_item_value: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    materials: list[Material] = Field(min_length=1)


class RecipeState(BaseModel):
    type_id: int
    recipe: Recipe | None
    synced_at: datetime
    expires_at: datetime


class ManufacturingQuery(LiquidityQuery):
    @model_validator(mode="before")
    @classmethod
    def discard_legacy_skill_settings(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
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
    include_invention_cost: bool = False
    material_order_type: Literal["buy", "sell"] = "sell"
    product_order_type: Literal["buy", "sell"] = "sell"
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
    def profit_ranges(self) -> "ManufacturingQuery":
        for low, high in ((self.min_profit, self.max_profit), (self.min_margin, self.max_margin)):
            if low is not None and high is not None and low > high:
                raise ValueError("Minimum must not exceed maximum")
        if self.sales_tax + self.sell_broker_fee > 100:
            raise ValueError("Combined sales tax and broker fee must not exceed 100%")
        return self


class MaterialCost(BaseModel):
    type_id: int
    quantity: int
    price: Decimal
    cost: Decimal
    volume_at_price: int


class ProfitCalculation(BaseModel):
    units: int
    seconds: Decimal
    materials: list[MaterialCost]
    material_cost_per_unit: Decimal
    job_cost_per_unit: Decimal
    base_job_cost_per_unit: Decimal = Decimal(0)
    facility_tax_per_unit: Decimal = Decimal(0)
    system_cost_per_unit: Decimal = Decimal(0)
    estimated_item_value_per_unit: Decimal | None = None
    invention_cost_per_unit: Decimal
    procurement_broker_fee_per_unit: Decimal
    sales_tax_per_unit: Decimal
    sales_broker_fee_per_unit: Decimal
    total_cost_per_unit: Decimal
    revenue_per_unit: Decimal
    profit_per_unit: Decimal
    margin_pct: Decimal
    profit_per_day: Decimal


class Opportunity(ProfitCalculation):
    type_id: int
    name: str
    blueprint_id: int
    meta_group_id: int | None
    invention_included: bool = False
    invention_required: bool | None
    invention_status: str = "not_requested"
    invention_decryptor: str | None = None
    invention_pricing_complete: bool | None = None
    recipe_synced_at: datetime
    daily_isk_volume: Decimal | None
    daily_units: Decimal | None
    product_volume_at_price: int
    product_order_count: int | None
    orders_at_price: int | None
    full_runs_at_buy_price: int | None
    production_limit_units: int | None
    profit_at_current_buy_price: Decimal | None
    demand_limited_profit_per_day: Decimal | None
    rank_profit_per_day: Decimal
    buy_demand_volume: int | None = None
    buy_demand_min_price: Decimal | None = None
    buy_demand_average_price: Decimal | None = None
    buy_demand_depth_available: bool | None = None
    demand_warnings: list[str] = Field(default_factory=list)
    stale: bool


class OpportunityPage(BaseModel):
    hub_id: HubId
    material_hub_id: HubId
    material_order_type: Literal["buy", "sell"]
    product_order_type: Literal["buy", "sell"]
    efficiency_basis: str = "base materials and production time; no ME/TE bonuses"
    sales_tax: Decimal
    broker_fee: Decimal
    buy_broker_fee: Decimal = Decimal(0)
    sell_broker_fee: Decimal = Decimal(0)
    facility_tax: Decimal = Decimal(0)
    system_cost_index: Decimal = Decimal(0)
    margin_basis: str = "material_cost"
    job_cost_basis: str = "EVE Ref base/SCC charge plus EIV-based facility tax and system cost"
    items: list[Opportunity]
    total: int
    missing_recipes: int
    non_manufacturable: int
    missing_prices: int
    missing_job_costs: int = 0
    missing_invention: int = 0
    invention_unavailable: dict[int, str] = Field(default_factory=dict)
    limit: int
    offset: int


class CalculationInput(BaseModel):
    recipe: Recipe
    quotes: dict[int, MarketPrice]
    product_quote: MarketPrice
    invention_cost_per_unit: Decimal = Field(default=Decimal(0), ge=0, allow_inf_nan=False)


class BuyDemandEstimate(BaseModel):
    volume: int
    order_count: int | None
    full_runs: int
    units: int
    profit: Decimal
    daily_profit: Decimal
    min_price: Decimal | None
    average_price: Decimal | None
    depth_available: bool
