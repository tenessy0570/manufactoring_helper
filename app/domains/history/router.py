from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Path, Query

from app.domains.history.models import HistorySeries, LiquidityPage, LiquidityQuery
from app.domains.history.service import HistoryService
from app.domains.market.models import HubId

router = APIRouter(prefix="/api/v1/market", tags=["history"], route_class=DishkaRoute)


@router.get("/liquidity", name="liquidity")
async def get_liquidity(
    service: FromDishka[HistoryService], query: Annotated[LiquidityQuery, Query()]
) -> LiquidityPage:
    return await service.get_liquidity(query)


@router.get("/history/{type_id}", name="history")
async def get_history_series(
    service: FromDishka[HistoryService],
    type_id: Annotated[int, Path(gt=0)],
    hub_id: HubId = "jita",
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> HistorySeries:
    return await service.get_history_series(hub_id, type_id, days)
