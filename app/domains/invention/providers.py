from collections.abc import AsyncIterator

from arq.connections import ArqRedis
from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import CacheService
from app.core.config import RefreshPolicy, Settings
from app.core.repository import UnitOfWork
from app.domains.invention.gateway import EverefInventionGateway, InventionGateway
from app.domains.invention.queue import InventionQueue, RedisInventionQueue
from app.domains.invention.repository import InventionRepository, SQLInventionRepository
from app.domains.invention.service import InventionService, InventionSyncService
from app.domains.invention.shopping import ShoppingService
from app.domains.manufacturing.gateway import IndustryClient
from app.domains.manufacturing.repository import ManufacturingRepository


class InventionProvider(Provider):
    @provide(scope=Scope.APP)
    async def provide_job_queue_client(self, settings: Settings) -> AsyncIterator[ArqRedis]:
        redis = ArqRedis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password.get_secret_value(),
        )
        yield redis
        await redis.aclose()

    @provide(scope=Scope.APP)
    def provide_queue(self, redis: ArqRedis) -> InventionQueue:
        return RedisInventionQueue(redis)

    @provide(scope=Scope.APP)
    def provide_gateway(self, client: IndustryClient) -> InventionGateway:
        return EverefInventionGateway(client)

    @provide(scope=Scope.REQUEST)
    def provide_repository(self, session: AsyncSession) -> InventionRepository:
        return SQLInventionRepository(session)

    @provide(scope=Scope.REQUEST)
    def provide_service(
        self,
        repository: InventionRepository,
        queue: InventionQueue,
        unit_of_work: UnitOfWork,
        cache: CacheService,
    ) -> InventionService:
        return InventionService(repository, queue, unit_of_work, cache)

    @provide(scope=Scope.REQUEST)
    def provide_sync_service(
        self,
        repository: InventionRepository,
        gateway: InventionGateway,
        manufacturing: ManufacturingRepository,
        unit_of_work: UnitOfWork,
        settings: Settings,
        refresh_policy: RefreshPolicy,
    ) -> InventionSyncService:
        return InventionSyncService(
            repository,
            gateway,
            manufacturing,
            unit_of_work,
            settings.invention_plan_ttl_seconds,
            refresh_policy=refresh_policy,
        )

    @provide(scope=Scope.REQUEST)
    def provide_shopping_service(
        self,
        repository: InventionRepository,
        market: ManufacturingRepository,
        refresh_policy: RefreshPolicy,
    ) -> ShoppingService:
        return ShoppingService(repository, market, refresh_policy)
