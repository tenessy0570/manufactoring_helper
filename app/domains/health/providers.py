from dishka import Provider, Scope, provide
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from app.core.config import RefreshPolicy
from app.domains.health.checks import DatabaseHealthCheck, RedisHealthCheck
from app.domains.health.repository import ProgressRepository, SQLProgressRepository
from app.domains.health.service import HealthService, ProgressService


class HealthProvider(Provider):
    scope = Scope.APP

    @provide
    def health_service(self, engine: AsyncEngine, redis: Redis) -> HealthService:
        return HealthService([DatabaseHealthCheck(engine), RedisHealthCheck(redis)])

    @provide(scope=Scope.REQUEST)
    def progress_repository(
        self, session: AsyncSession, refresh_policy: RefreshPolicy
    ) -> ProgressRepository:
        return SQLProgressRepository(session, refresh_policy)

    @provide(scope=Scope.REQUEST)
    def progress_service(self, repository: ProgressRepository) -> ProgressService:
        return ProgressService(repository)
