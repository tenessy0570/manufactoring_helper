from app.core.di import create_container
from app.domains.health.checks import DatabaseHealthCheck, RedisHealthCheck
from app.domains.health.service import HealthService
from tests.helpers import make_settings


async def test_health_service_checks_database_and_redis() -> None:
    container = create_container(make_settings())

    service = await container.get(HealthService)

    assert [type(check) for check in service._checks] == [DatabaseHealthCheck, RedisHealthCheck]
    await container.close()
