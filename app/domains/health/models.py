from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class HealthStatus(StrEnum):
    OK = "ok"
    FAIL = "fail"


class ComponentHealth(BaseModel):
    name: str
    status: HealthStatus
    detail: str | None = None


class HealthReport(BaseModel):
    status: HealthStatus
    components: list[ComponentHealth]


class DataProgress(BaseModel):
    catalog_items: int
    recipes_loaded: int
    recipes_unavailable: int
    history_loaded: int
    invention_ready: int
    invention_pending: int
    invention_unsupported: int
    invention_errors: int
    t2_items: int
    market_items: int
    market_updated_at: datetime | None


class SourceFreshness(BaseModel):
    source: str
    oldest_at: datetime | None
    newest_at: datetime | None
    cached: int
    fresh: int
    status: Literal["fresh", "partial", "stale", "missing"]


class FreshnessReport(BaseModel):
    hub_id: str
    checked_at: datetime
    sources: list[SourceFreshness]
