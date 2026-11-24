from datetime import date, datetime
from decimal import Decimal

from pydantic import AwareDatetime, BaseModel, Field

from app.contracts.opportunities import LiquidityFilters
from app.domains.market.models import TradeHub


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


class LiquidityQuery(LiquidityFilters):
    pass


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
