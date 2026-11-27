import asyncio
from collections.abc import Sequence
from datetime import UTC, datetime

from app.domains.health.checks import HealthCheck
from app.domains.health.models import (
    ComponentHealth,
    DataProgress,
    FreshnessReport,
    HealthReport,
    HealthStatus,
)
from app.domains.health.repository import ProgressRepository
from app.domains.market.models import HubId
from app.domains.market.progress import MarketSyncProgress


class HealthService:
    def __init__(self, checks: Sequence[HealthCheck], timeout_seconds: float = 3.0) -> None:
        self._checks = checks
        self._timeout_seconds = timeout_seconds

    async def check_readiness(self) -> HealthReport:
        components = await asyncio.gather(*(self._run(check) for check in self._checks))
        failed = any(component.status is HealthStatus.FAIL for component in components)
        return HealthReport(
            status=HealthStatus.FAIL if failed else HealthStatus.OK,
            components=list(components),
        )

    async def _run(self, check: HealthCheck) -> ComponentHealth:
        try:
            await asyncio.wait_for(check.probe(), timeout=self._timeout_seconds)
        except Exception as error:
            # Only the exception type is exposed: messages may contain connection details.
            return ComponentHealth(
                name=check.name, status=HealthStatus.FAIL, detail=type(error).__name__
            )
        return ComponentHealth(name=check.name, status=HealthStatus.OK)


class ProgressService:
    def __init__(
        self, repository: ProgressRepository, progress: MarketSyncProgress | None = None
    ) -> None:
        self._repository = repository
        self._progress = progress

    async def get_data_progress(self, hub: HubId) -> DataProgress:
        return await self._repository.get_data_progress(hub)

    async def get_freshness_report(self, hub: HubId) -> FreshnessReport:
        report = await self._repository.get_freshness_report(hub, datetime.now(UTC))
        if self._progress is not None:
            progress = await self._progress.get(hub)
            if progress is not None:
                for source in report.sources:
                    if source.source == "market":
                        source.completed_pages, source.total_pages = progress
        return report
