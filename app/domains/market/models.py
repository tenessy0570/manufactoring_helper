from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

HubId = Literal["jita", "amarr", "dodixie", "rens", "hek"]


class TradeHub(BaseModel):
    model_config = ConfigDict(frozen=True)

    hub_id: HubId
    name: str
    region_id: int
    station_id: int


HUBS = (
    TradeHub(hub_id="jita", name="Jita", region_id=10000002, station_id=60003760),
    TradeHub(hub_id="amarr", name="Amarr", region_id=10000043, station_id=60008494),
    TradeHub(hub_id="dodixie", name="Dodixie", region_id=10000032, station_id=60011866),
    TradeHub(hub_id="rens", name="Rens", region_id=10000030, station_id=60004588),
    TradeHub(hub_id="hek", name="Hek", region_id=10000042, station_id=60005686),
)


def get_hub(hub_id: HubId) -> TradeHub:
    return next(hub for hub in HUBS if hub.hub_id == hub_id)


class MarketOrder(BaseModel):
    order_id: int
    type_id: int
    location_id: int
    is_buy_order: bool
    price: Decimal = Field(gt=0, allow_inf_nan=False)
    volume_remain: int = Field(ge=0)


class OrderPage(BaseModel):
    orders: list[MarketOrder]
    page: int = Field(ge=1)
    pages: int = Field(ge=1)
    expires_at: AwareDatetime


class MarketPrice(BaseModel):
    hub_id: HubId
    type_id: int
    buy_price: Decimal | None = None
    sell_price: Decimal | None = None
    buy_volume: int = 0
    sell_volume: int = 0
    buy_order_count: int | None = None
    sell_order_count: int | None = None
    buy_orders_at_best: int | None = None
    sell_orders_at_best: int | None = None
    spread: Decimal | None = None
    synced_at: datetime
    expires_at: datetime


class MarketState(BaseModel):
    hub_id: HubId
    synced_at: datetime
    expires_at: datetime
    items: int


class PriceQuery(BaseModel):
    hub_id: HubId = "jita"
    type_ids: list[int] | None = Field(default=None, max_length=1000)
    exclude_type_ids: list[int] | None = Field(default=None, max_length=1000)
    min_buy_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_buy_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    min_sell_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    max_sell_price: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    min_spread: Decimal | None = Field(default=None, allow_inf_nan=False)
    max_spread: Decimal | None = Field(default=None, allow_inf_nan=False)
    min_buy_volume: int | None = Field(default=None, ge=0)
    min_sell_volume: int | None = Field(default=None, ge=0)
    has_buy: bool | None = None
    has_sell: bool | None = None
    fresh_only: bool = False
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> "PriceQuery":
        for low, high in (
            (self.min_buy_price, self.max_buy_price),
            (self.min_sell_price, self.max_sell_price),
            (self.min_spread, self.max_spread),
        ):
            if low is not None and high is not None and low > high:
                raise ValueError("Minimum must not exceed maximum")
        return self


class PricePage(BaseModel):
    hub: TradeHub
    state: MarketState | None
    stale: bool
    items: list[MarketPrice]
    total: int
    limit: int
    offset: int


class MarketSyncReport(BaseModel):
    hub_id: HubId
    skipped: bool = False
    items: int = 0
    pages: int = 0
