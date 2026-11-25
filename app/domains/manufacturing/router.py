from typing import Annotated

import httpx
from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Path, Query

from app.domains.manufacturing.gateway import AmbiguousRecipeError
from app.domains.manufacturing.models import (
    CalculatorPage,
    CalculatorQuery,
    ManufacturingQuery,
    OpportunityPage,
)
from app.domains.manufacturing.service import ManufacturingService
from app.infrastructure.http import HttpStatusError

router = APIRouter(prefix="/api/v1/manufacturing", tags=["manufacturing"], route_class=DishkaRoute)


@router.get("/opportunities", name="opportunities")
async def get_opportunities(
    service: FromDishka[ManufacturingService], query: Annotated[ManufacturingQuery, Query()]
) -> OpportunityPage:
    return await service.get_opportunities(query)


@router.get("/calculator/{type_id}", name="calculator")
async def get_calculator_page(
    type_id: Annotated[int, Path(gt=0)],
    service: FromDishka[ManufacturingService],
    query: Annotated[CalculatorQuery, Query()],
) -> CalculatorPage:
    try:
        return await service.get_calculator_page(type_id, query)
    except AmbiguousRecipeError as error:
        raise HTTPException(409, "This product has multiple source blueprints.") from error
    except (HttpStatusError, httpx.HTTPError) as error:
        raise HTTPException(
            503, "Could not refresh this blueprint recipe. Please try again shortly."
        ) from error
