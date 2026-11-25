from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from app.domains.market.models import HUBS, PricePage, PriceQuery, TradeHub
from app.domains.market.service import MarketService

router = APIRouter(prefix="/api/v1/market", tags=["market"], route_class=DishkaRoute)


@router.get("/hubs", name="hubs")
async def get_hubs() -> list[TradeHub]:
    return list(HUBS)


@router.get("/prices", name="prices")
async def get_prices(
    service: FromDishka[MarketService], query: Annotated[PriceQuery, Query()]
) -> PricePage:
    return await service.find(query)
