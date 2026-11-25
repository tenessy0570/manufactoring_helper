from typing import Annotated
from uuid import UUID

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query, Request, Response

from app.domains.production.models import (
    EntryInput,
    Estimate,
    EstimateInput,
    Production,
    ProductionCreate,
    ProductionDetails,
    ProductionPurchaseList,
    PurchaseListInput,
)
from app.domains.production.service import ProductionEstimateService, ProductionService

router = APIRouter(
    prefix="/api/v1/productions", tags=["production history"], route_class=DishkaRoute
)


@router.get("")
async def find(
    request: Request,
    service: FromDishka[ProductionService],
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[Production]:
    return await service.find(request.state.user.id, offset, limit)


@router.post("", status_code=201)
async def create(
    data: ProductionCreate, request: Request, service: FromDishka[ProductionService]
) -> Production:
    return await service.create(request.state.user.id, data)


@router.get("/{production_id}")
async def get(
    production_id: UUID, request: Request, service: FromDishka[ProductionService]
) -> Production:
    return await service.get(request.state.user.id, production_id)


@router.put("/{production_id}")
async def update(
    production_id: UUID,
    data: ProductionDetails,
    request: Request,
    service: FromDishka[ProductionService],
) -> Production:
    return await service.update(request.state.user.id, production_id, data)


@router.delete("/{production_id}", status_code=204)
async def delete(
    production_id: UUID, request: Request, service: FromDishka[ProductionService]
) -> Response:
    await service.delete(request.state.user.id, production_id)
    return Response(status_code=204)


@router.post("/{production_id}/entries", status_code=201)
async def add_entry(
    production_id: UUID, data: EntryInput, request: Request, service: FromDishka[ProductionService]
) -> Production:
    return await service.save_entry(request.state.user.id, production_id, data)


@router.put("/{production_id}/entries/{entry_id}")
async def edit_entry(
    production_id: UUID,
    entry_id: UUID,
    data: EntryInput,
    request: Request,
    service: FromDishka[ProductionService],
) -> Production:
    return await service.save_entry(request.state.user.id, production_id, data, entry_id)


@router.delete("/{production_id}/entries/{entry_id}")
async def delete_entry(
    production_id: UUID, entry_id: UUID, request: Request, service: FromDishka[ProductionService]
) -> Production:
    return await service.delete_entry(request.state.user.id, production_id, entry_id)


@router.post("/{production_id}/estimate", name="estimate")
async def estimate_cost(
    production_id: UUID,
    data: EstimateInput,
    request: Request,
    service: FromDishka[ProductionEstimateService],
) -> Estimate:
    return await service.estimate_cost(request.state.user.id, production_id, data)


@router.post("/{production_id}/purchase-list", name="purchase_list")
async def get_purchase_list(
    production_id: UUID,
    data: PurchaseListInput,
    request: Request,
    service: FromDishka[ProductionEstimateService],
) -> ProductionPurchaseList:
    return await service.get_purchase_list(request.state.user.id, production_id, data)
