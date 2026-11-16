from collections.abc import AsyncIterator

import pytest
from dishka import Provider, Scope, make_async_container
from httpx import ASGITransport, AsyncClient

from app.domains.health.checks import HealthCheck
from app.domains.health.service import HealthService
from app.main import create_app
from tests.helpers import make_settings


class StubCheck(HealthCheck):
    name = "stub"

    def __init__(self, healthy: bool) -> None:
        self._healthy = healthy

    async def probe(self) -> None:
        if not self._healthy:
            raise ConnectionError("down")


def make_client(healthy: bool) -> AsyncClient:
    service = HealthService([StubCheck(healthy)])
    provider = Provider(scope=Scope.APP)
    provider.provide(lambda: service, provides=HealthService)
    app = create_app(container=make_async_container(provider), settings=make_settings())
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture
async def healthy_client() -> AsyncIterator[AsyncClient]:
    async with make_client(healthy=True) as client:
        yield client


@pytest.fixture
async def unhealthy_client() -> AsyncIterator[AsyncClient]:
    async with make_client(healthy=False) as client:
        yield client


async def test_liveness_always_reports_ok(unhealthy_client: AsyncClient) -> None:
    response = await unhealthy_client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_readiness_returns_200_when_dependencies_are_healthy(
    healthy_client: AsyncClient,
) -> None:
    response = await healthy_client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


async def test_readiness_returns_503_with_details_when_a_dependency_fails(
    unhealthy_client: AsyncClient,
) -> None:
    response = await unhealthy_client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "fail",
        "components": [{"name": "stub", "status": "fail", "detail": "ConnectionError"}],
    }
