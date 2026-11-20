from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.domains.market.models import HubId, MarketPrice

RouteMode = Literal["safe", "shortest"]


class TradeRoute(BaseModel):
    jumps: int | None = Field(default=None, ge=1)
    highsec: bool | None = None
    error: str | None = None


class TradingQuery(BaseModel):
    price_spikes_only: bool = False
    price_spike_threshold: Decimal = Field(default=Decimal(30), ge=0, allow_inf_nan=False)
    route_mode: RouteMode = "safe"
    max_jumps: int | None = Field(default=None, ge=1)
    min_profit_per_jump: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    source_hub: HubId | None = None
    destination_hub: HubId | None = None
    purchase_side: Literal["sell", "buy"] = "sell"
    sale_side: Literal["buy", "sell"] = "buy"
    search: str = Field(default="", max_length=200)
    buy_broker_fee: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    sell_broker_fee: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    sales_tax: Decimal = Field(default=Decimal(0), ge=0, le=100, allow_inf_nan=False)
    buy_price_range: Decimal = Field(default=Decimal(5), ge=0, le=100, allow_inf_nan=False)
    history_days: int = Field(default=30, ge=1, le=365)
    filter_daily_turnover: bool = False
    min_daily_isk_volume: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    min_profit: Decimal | None = Field(default=None, allow_inf_nan=False)
    min_margin: Decimal | None = Field(default=None, allow_inf_nan=False)
    min_batch_profit: Decimal | None = Field(default=None, allow_inf_nan=False)
    max_investment: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_cargo_m3: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    max_units: int | None = Field(default=None, ge=1)
    fresh_only: bool = False
    rank_by: Literal[
        "batch_profit", "profit", "margin", "profit_per_m3", "profit_per_jump", "jumps"
    ] = "batch_profit"
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="before")
    @classmethod
    def empty_hubs(cls, value: Any) -> Any:
        if isinstance(value, dict):
            value = dict(value)
            for key in ("source_hub", "destination_hub"):
                if value.get(key) == "":
                    value[key] = None
        return value

    @model_validator(mode="after")
    def validate_route(self) -> "TradingQuery":
        if self.source_hub is not None and self.source_hub == self.destination_hub:
            raise ValueError("Choose two different hubs")
        if self.sales_tax + self.sell_broker_fee > 100:
            raise ValueError("Combined sales tax and sell broker must not exceed 100%")
        return self


class TradeMetadata(BaseModel):
    type_id: int
    name: str
    volume_m3: Decimal | None
    updated_at: datetime
    expires_at: datetime


class TradeInput(BaseModel):
    source: MarketPrice
    destination: MarketPrice
    name: str | None = None
    volume_m3: Decimal | None = None
    metadata_expires_at: datetime | None = None


class TradeOpportunity(BaseModel):
    source_hub: HubId
    destination_hub: HubId
    type_id: int
    name: str
    purchase_price: Decimal
    sale_price: Decimal
    purchase_fee: Decimal
    sale_fee: Decimal
    cost_per_unit: Decimal
    profit_per_unit: Decimal
    margin_pct: Decimal
    volume_m3: Decimal | None
    profit_per_m3: Decimal | None
    quantity: int | None
    investment: Decimal | None
    cargo_m3: Decimal | None
    batch_revenue: Decimal | None
    batch_profit: Decimal | None
    average_sale_price: Decimal | None
    source_stock: int | None
    destination_demand: int | None
    source_updated_at: datetime
    destination_updated_at: datetime
    stale: bool
    jumps: int | None = None
    route_highsec: bool | None = None
    profit_per_jump: Decimal | None = None
    price_spike_pct: Decimal | None = None
    historical_median_price: Decimal | None = None
    daily_isk_volume: Decimal | None = None
    history_updated_at: datetime | None = None
    instant_trade: bool
    warnings: list[str]


class TradingPage(BaseModel):
    source_hub: HubId | None
    destination_hub: HubId | None
    items: list[TradeOpportunity]
    total: int
    limit: int
    offset: int
    scanned: int
    missing_metadata: int
    missing_volume: int
    missing_history: int = 0
    missing_routes: int = 0
    source_updated_at: datetime | None
    destination_updated_at: datetime | None


class TradeTypeDetails(BaseModel):
    name: str
    volume: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    packaged_volume: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)


class TradeTurnover(BaseModel):
    median_price: Decimal | None = None
    baseline_days: int = 0
    type_id: int
    region_id: int
    daily_isk_volume: Decimal
    updated_at: datetime
