from collections.abc import AsyncIterator

import pytest
from dishka import AsyncContainer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.cache import Cache, CacheService, TieredCache
from app.core.config import Settings
from app.core.di import create_container
from app.core.repository import SQLAlchemyUnitOfWork, UnitOfWork
from tests.helpers import make_settings


@pytest.fixture
async def container() -> AsyncIterator[AsyncContainer]:
    container = create_container(make_settings(redis_host="redis.test", redis_port=6380))
    yield container
    await container.close()


async def test_settings_come_from_the_container_context(container: AsyncContainer) -> None:
    settings = await container.get(Settings)

    assert settings.redis_host == "redis.test"


async def test_engine_and_session_factory_use_configured_database(
    container: AsyncContainer,
) -> None:
    engine = await container.get(AsyncEngine)
    factory = await container.get(async_sessionmaker[AsyncSession])

    assert engine.url.drivername == "postgresql+asyncpg"
    assert factory.kw["bind"] is engine


async def test_redis_client_is_configured_from_settings(container: AsyncContainer) -> None:
    client = await container.get(Redis)

    kwargs = client.connection_pool.connection_kwargs
    assert (kwargs["host"], kwargs["port"]) == ("redis.test", 6380)
    assert kwargs["password"] == "redis-secret"


async def test_cache_is_tiered_and_shared_through_the_cache_service(
    container: AsyncContainer,
) -> None:
    assert isinstance(await container.get(Cache), TieredCache)
    assert isinstance(await container.get(CacheService), CacheService)


async def test_request_scope_provides_a_session_and_unit_of_work(
    container: AsyncContainer,
) -> None:
    async with container() as request_container:
        session = await request_container.get(AsyncSession)
        unit_of_work = await request_container.get(UnitOfWork)

        assert isinstance(unit_of_work, SQLAlchemyUnitOfWork)
        assert await request_container.get(AsyncSession) is session
