from typing import Annotated

from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Query

from app.core.repository import Page
from app.domains.catalog.models import CatalogPage, CatalogQuery, ItemTypeClause
from app.domains.catalog.service import CatalogService

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"], route_class=DishkaRoute)


@router.get("/items")
async def items(
    service: FromDishka[CatalogService],
    filters: Annotated[CatalogQuery, Query()],
) -> CatalogPage:
    clause = ItemTypeClause.model_validate(filters.model_dump(exclude={"limit", "offset"}))
    return await service.find(clause, Page(limit=filters.limit, offset=filters.offset))
