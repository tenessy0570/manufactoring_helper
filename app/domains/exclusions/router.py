from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Request

from app.domains.exclusions.models import ExclusionList
from app.domains.exclusions.service import ExclusionService

router = APIRouter(
    prefix="/api/v1/opportunity-exclusions", tags=["exclusions"], route_class=DishkaRoute
)


@router.get("")
async def get_exclusions(request: Request, service: FromDishka[ExclusionService]) -> ExclusionList:
    if not getattr(request.state, "user", None):
        raise HTTPException(401, "Login required")
    return await service.get(request.state.user.id)


@router.put("")
async def save_exclusions(
    request: Request, data: ExclusionList, service: FromDishka[ExclusionService]
) -> ExclusionList:
    if not getattr(request.state, "user", None):
        raise HTTPException(401, "Login required")
    return await service.save(request.state.user.id, data)
