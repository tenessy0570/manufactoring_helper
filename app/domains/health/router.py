from dishka.integrations.fastapi import DishkaRoute, FromDishka
from fastapi import APIRouter, Response, status

from app.domains.health.models import DataProgress, FreshnessReport, HealthReport, HealthStatus
from app.domains.health.service import HealthService, ProgressService
from app.domains.market.models import HubId

router = APIRouter(prefix="/health", tags=["health"], route_class=DishkaRoute)


@router.get("/live", name="liveness")
async def get_liveness_status() -> dict[str, str]:
    return {"status": HealthStatus.OK}


@router.get("/ready", name="readiness")
async def check_readiness(service: FromDishka[HealthService], response: Response) -> HealthReport:
    report = await service.check_readiness()
    if report.status is HealthStatus.FAIL:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report


@router.get("/data-progress", name="data_progress")
async def get_data_progress(
    service: FromDishka[ProgressService], hub: HubId = "jita"
) -> DataProgress:
    return await service.get_data_progress(hub)


@router.get("/freshness", name="freshness")
async def get_freshness_report(
    service: FromDishka[ProgressService], hub: HubId = "jita"
) -> FreshnessReport:
    return await service.get_freshness_report(hub)
