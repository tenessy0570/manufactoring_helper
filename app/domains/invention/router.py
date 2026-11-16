from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Path, Query

from app.domains.invention.models import InventionQuery, InventionSettings, InventionView
from app.domains.invention.queue import InventionQueue
from app.domains.invention.service import InventionService

router = APIRouter(prefix="/api/v1/invention", tags=["invention"], route_class=DishkaRoute)


@router.post("/prepare", status_code=202)
async def prepare_catalog(
    queue: FromDishka[InventionQueue], query: Annotated[InventionQuery, Query()]
) -> dict[str, bool]:
    return {"queued": await queue.enqueue_catalog(query)}


@router.get("/{type_id}")
async def view(
    service: FromDishka[InventionService],
    type_id: Annotated[int, Path(gt=0)],
    query: Annotated[InventionQuery, Query()],
) -> InventionView:
    return await service.view(InventionSettings(type_id=type_id, **query.model_dump()))


@router.post("/{type_id}/prepare", status_code=202)
async def prepare(
    service: FromDishka[InventionService],
    type_id: Annotated[int, Path(gt=0)],
    query: Annotated[InventionQuery, Query()],
) -> InventionView:
    return await service.prepare(InventionSettings(type_id=type_id, **query.model_dump()))
