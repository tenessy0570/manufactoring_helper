from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Response, status

from app.domains.health.models import HealthReport, HealthStatus
from app.domains.health.service import HealthService

router = APIRouter(prefix="/health", tags=["health"], route_class=DishkaRoute)


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": HealthStatus.OK}


@router.get("/ready")
async def readiness(service: FromDishka[HealthService], response: Response) -> HealthReport:
    report = await service.readiness()
    if report.status is HealthStatus.FAIL:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
