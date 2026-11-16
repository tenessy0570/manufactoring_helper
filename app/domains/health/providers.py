from dishka import Provider, Scope, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domains.health.checks import DatabaseHealthCheck, RedisHealthCheck
from app.domains.health.service import HealthService


class HealthProvider(Provider):
    scope = Scope.APP

    @provide
    def health_service(self, engine: AsyncEngine, redis: Redis) -> HealthService:
        return HealthService([DatabaseHealthCheck(engine), RedisHealthCheck(redis)])
