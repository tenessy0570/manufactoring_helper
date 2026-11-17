from datetime import datetime

from pydantic import BaseModel, Field, PositiveInt

from app.core.repository import FilterClause

MASS_PRODUCTION_META_GROUP_IDS = (1, 2)


class MarketGroup(BaseModel):
    market_group_id: int
    name: str
    parent_group_id: int | None = None
    types: list[int] = Field(default_factory=list)


class CatalogCandidate(BaseModel):
    type_id: int
    market_group_id: int
    market_group_name: str
    category: str
    group_path: list[int]
    is_rig: bool


class ItemType(CatalogCandidate):
    name: str
    meta_group_id: int | None = None
    is_active: bool = True
    synced_at: datetime


class ItemTypeClause(FilterClause):
    search: str | None = Field(default=None, min_length=1, max_length=200)
    type_ids: list[int] | None = Field(default=None, max_length=1000)
    exclude_type_ids: list[int] | None = Field(default=None, max_length=1000)
    categories: list[str] | None = Field(default=None, max_length=100)
    market_group_ids: list[int] | None = Field(default=None, max_length=1000)
    meta_group_ids: list[int] | None = Field(default=None, max_length=100)
    is_rig: bool | None = None
    has_meta_group: bool | None = None
    is_active: bool | None = True


class CatalogPage(BaseModel):
    items: list[ItemType]
    total: int
    limit: int
    offset: int


class CatalogQuery(ItemTypeClause):
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)


class CatalogSyncReport(BaseModel):
    skipped: bool = False
    items: int = 0
    missing_metadata: int = 0


class ItemNamesQuery(BaseModel):
    type_ids: list[PositiveInt] = Field(min_length=1, max_length=1000)


class ItemNamesResult(BaseModel):
    names: dict[int, str]
    missing_type_ids: list[int]
