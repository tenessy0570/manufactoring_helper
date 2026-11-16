from abc import ABC, abstractmethod

from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class HealthCheck(ABC):
    """Probes one dependency. Raising any exception means the dependency is unhealthy."""

    name: str

    @abstractmethod
    async def probe(self) -> None: ...


class DatabaseHealthCheck(HealthCheck):
    name = "database"

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def probe(self) -> None:
        async with self._engine.connect() as connection:
            await connection.execute(text("SELECT 1"))


class RedisHealthCheck(HealthCheck):
    name = "redis"

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def probe(self) -> None:
        await self._client.ping()
