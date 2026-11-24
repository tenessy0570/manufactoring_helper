from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, HTTPException, Query, Response

from app.application.profile_calculation import ProfileCalculationService
from app.domains.manufacturing.models import OpportunityPage
from app.domains.profiles.models import (
    Profile,
    ProfileCreate,
    ProfileName,
    ProfilePage,
    ProfileUpdate,
)
from app.domains.profiles.service import (
    LastProfileError,
    ProfileNotFoundError,
    ProfileService,
)

router = APIRouter(prefix="/api/v1/profiles", tags=["profiles"], route_class=DishkaRoute)


@router.get("")
async def profiles(service: FromDishka[ProfileService]) -> ProfilePage:
    return await service.find()


@router.post("", status_code=201)
async def create(data: ProfileCreate, service: FromDishka[ProfileService]) -> Profile:
    return await service.create(data)


@router.get("/default")
async def default(service: FromDishka[ProfileService]) -> Profile:
    return await service.get()


@router.get("/default/opportunities")
async def default_opportunities(
    service: FromDishka[ProfileCalculationService],
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OpportunityPage:
    return await service.opportunities(None, limit, offset)


@router.get("/{profile_id}")
async def get(profile_id: UUID, service: FromDishka[ProfileService]) -> Profile:
    try:
        return await service.get(profile_id)
    except ProfileNotFoundError as error:
        raise HTTPException(404, "Profile not found") from error


@router.patch("/{profile_id}")
async def update(
    profile_id: UUID, data: ProfileUpdate, service: FromDishka[ProfileService]
) -> Profile:
    try:
        return await service.update(profile_id, data)
    except ProfileNotFoundError as error:
        raise HTTPException(404, "Profile not found") from error


@router.post("/{profile_id}/copy", status_code=201)
async def copy(profile_id: UUID, data: ProfileName, service: FromDishka[ProfileService]) -> Profile:
    try:
        return await service.copy(profile_id, data.name)
    except ProfileNotFoundError as error:
        raise HTTPException(404, "Profile not found") from error


@router.put("/{profile_id}/default")
async def set_default(profile_id: UUID, service: FromDishka[ProfileService]) -> Profile:
    try:
        return await service.set_default(profile_id)
    except ProfileNotFoundError as error:
        raise HTTPException(404, "Profile not found") from error


@router.delete("/{profile_id}", status_code=204)
async def delete(profile_id: UUID, service: FromDishka[ProfileService]) -> Response:
    try:
        await service.delete(profile_id)
    except ProfileNotFoundError as error:
        raise HTTPException(404, "Profile not found") from error
    except LastProfileError as error:
        raise HTTPException(409, "Cannot delete the last profile") from error
    return Response(status_code=204)


@router.get("/{profile_id}/opportunities")
async def opportunities(
    profile_id: UUID,
    service: FromDishka[ProfileCalculationService],
    limit: Annotated[int | None, Query(ge=1, le=1000)] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OpportunityPage:
    try:
        return await service.opportunities(profile_id, limit, offset)
    except ProfileNotFoundError as error:
        raise HTTPException(404, "Profile not found") from error
