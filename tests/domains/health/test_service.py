import asyncio

from app.domains.health.checks import HealthCheck
from app.domains.health.models import HealthStatus
from app.domains.health.service import HealthService


class StubCheck(HealthCheck):
    def __init__(self, name: str, error: Exception | None = None, delay: float = 0.0) -> None:
        self.name = name
        self._error = error
        self._delay = delay

    async def probe(self) -> None:
        await asyncio.sleep(self._delay)
        if self._error:
            raise self._error


async def test_all_checks_passing_reports_ok() -> None:
    service = HealthService([StubCheck("database"), StubCheck("redis")])

    report = await service.check_readiness()

    assert report.status is HealthStatus.OK
    assert [component.name for component in report.components] == ["database", "redis"]
    assert all(component.status is HealthStatus.OK for component in report.components)


async def test_one_failing_check_fails_the_report_and_exposes_only_the_error_type() -> None:
    service = HealthService(
        [StubCheck("database"), StubCheck("redis", error=ConnectionError("password=hunter2"))]
    )

    report = await service.check_readiness()

    failed = next(component for component in report.components if component.name == "redis")
    assert report.status is HealthStatus.FAIL
    assert failed.status is HealthStatus.FAIL
    assert failed.detail == "ConnectionError"


async def test_slow_check_times_out_and_is_reported_as_failed() -> None:
    service = HealthService([StubCheck("database", delay=1)], timeout_seconds=0.01)

    report = await service.check_readiness()

    assert report.status is HealthStatus.FAIL
    assert report.components[0].detail == "TimeoutError"


async def test_report_without_checks_is_ok() -> None:
    assert (await HealthService([]).check_readiness()).status is HealthStatus.OK
