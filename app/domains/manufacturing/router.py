from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from app.domains.manufacturing.models import ManufacturingQuery, OpportunityPage
from app.domains.manufacturing.service import ManufacturingService

router = APIRouter(prefix="/api/v1/manufacturing", tags=["manufacturing"], route_class=DishkaRoute)


@router.get("/opportunities")
async def opportunities(
    service: FromDishka[ManufacturingService], query: Annotated[ManufacturingQuery, Query()]
) -> OpportunityPage:
    return await service.opportunities(query)
