from datetime import date, datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, Field, model_validator

from app.domains.market.models import HubId, TradeHub


class HistoryDay(BaseModel):
    date: date
    average: Decimal = Field(ge=0, allow_inf_nan=False)
    highest: Decimal = Field(ge=0, allow_inf_nan=False)
    lowest: Decimal = Field(ge=0, allow_inf_nan=False)
    volume: int = Field(ge=0)
    order_count: int = Field(ge=0)


class HistoryDownload(BaseModel):
    days: list[HistoryDay]
    expires_at: AwareDatetime


class HistoryState(BaseModel):
    region_id: int
    type_id: int
    synced_at: datetime
    expires_at: datetime


class LiquidityQuery(BaseModel):
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
    def ranges(self) -> "LiquidityQuery":
        for low, high in (
            (self.min_daily_units, self.max_daily_units),
            (self.min_daily_isk_volume, self.max_daily_isk_volume),
        ):
            if low is not None and high is not None and low > high:
                raise ValueError("Minimum must not exceed maximum")
        return self


class LiquidityItem(BaseModel):
    type_id: int
    name: str
    meta_group_id: int | None = None
    data_days: int
    daily_isk_volume: Decimal | None
    daily_units: Decimal | None
    latest_trade_date: date | None
    synced_at: datetime | None
    expires_at: datetime | None


class LiquidityPage(BaseModel):
    hub: TradeHub
    scope: str = "region"
    start_date: date
    end_date: date
    days: int
    items: list[LiquidityItem]
    total: int
    limit: int
    offset: int


class HistorySeries(BaseModel):
    hub: TradeHub
    scope: str = "region"
    type_id: int
    state: HistoryState | None
    stale: bool
    days: list[HistoryDay]
