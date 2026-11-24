from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.contracts.opportunities import OpportunitySettings
from app.domains.history.models import LiquidityItem
from app.domains.invention.models import InventionRequest, InventionSettings
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


class ManufacturingQuery(OpportunitySettings):
    pass


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
    demand_duration_seconds: Decimal | None = None
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
    fresh_until: datetime | None = None
    freshness_deadlines: dict[str, datetime] = Field(default_factory=dict)


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
    revenue: Decimal = Decimal(0)
    volume: int
    order_count: int | None
    full_runs: int
    units: int
    profit: Decimal
    daily_profit: Decimal
    min_price: Decimal | None
    average_price: Decimal | None
    depth_available: bool


class CalculatorQuery(ManufacturingQuery):
    manufacturing_runs: int = Field(default=1, ge=1, le=1_000_000_000)


class BatchCalculation(BaseModel):
    runs: int
    units: int
    materials: list[MaterialCost]
    material_cost: Decimal
    base_job_cost: Decimal
    facility_tax: Decimal
    system_cost: Decimal
    job_cost: Decimal
    invention_cost: Decimal
    procurement_broker_fee: Decimal
    total_cost: Decimal
    gross_revenue: Decimal | None
    sales_tax: Decimal | None
    sales_broker_fee: Decimal | None
    net_revenue: Decimal | None
    profit: Decimal | None
    margin_pct: Decimal | None
    covered_units: int


class CalculatorPage(OpportunityPage):
    batch: BatchCalculation | None = None


class OpportunityInputs(BaseModel):
    candidates: list[LiquidityItem]
    recipes: dict[int, RecipeState]
    quotes: dict[int, MarketPrice]
    products: dict[int, MarketPrice]
    invention_settings: dict[int, InventionSettings]
    invention_results: dict[str, InventionRequest]


class OpportunityTiming(BaseModel):
    daily_profit: Decimal
    demand_daily_profit: Decimal | None
    duration_seconds: Decimal | None


class OpportunityEvaluation(BaseModel):
    items: list[Opportunity]
    missing_recipes: int
    non_manufacturable: int
    missing_prices: int
    missing_job_costs: int
    missing_invention: int
    invention_unavailable: dict[int, str]
