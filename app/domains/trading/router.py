from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from app.domains.trading.models import TradingPage, TradingQuery
from app.domains.trading.service import TradingService

router = APIRouter(prefix="/api/v1/trading", tags=["trading"], route_class=DishkaRoute)


@router.get("/opportunities", name="opportunities")
async def get_opportunities(
    service: FromDishka[TradingService], query: Annotated[TradingQuery, Query()]
) -> TradingPage:
    return await service.get_opportunities(query)


# Temporarily disabled pending Cargo planner redesign.
# @router.post("/cargo")
# async def cargo_plan(service: FromDishka[CargoService], query: CargoQuery) -> CargoResult:
#     return await service.plan(query)
