from enum import StrEnum

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
