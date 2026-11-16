from collections.abc import AsyncIterator

import httpx
from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.repository import UnitOfWork
from app.domains.history.repository import HistoryRepository
from app.domains.manufacturing.gateway import EverefIndustryGateway, IndustryClient, IndustryGateway
from app.domains.manufacturing.repository import ManufacturingRepository, SQLManufacturingRepository
from app.domains.manufacturing.service import ManufacturingService, ManufacturingSyncService


class ManufacturingProvider(Provider):
    @provide(scope=Scope.APP)
    async def client(self, settings: Settings) -> AsyncIterator[IndustryClient]:
        async with httpx.AsyncClient(
            base_url=settings.industry_base_url,
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.esi_user_agent},
        ) as http:
            yield IndustryClient(http, settings.industry_max_concurrency, settings.http_max_retries)

    @provide(scope=Scope.APP)
    def gateway(self, client: IndustryClient) -> IndustryGateway:
        return EverefIndustryGateway(client)

    @provide(scope=Scope.REQUEST)
    def repository(self, session: AsyncSession) -> ManufacturingRepository:
        return SQLManufacturingRepository(session)

    @provide(scope=Scope.REQUEST)
    def service(
        self, repository: ManufacturingRepository, history: HistoryRepository
    ) -> ManufacturingService:
        return ManufacturingService(repository, history)

    @provide(scope=Scope.REQUEST)
    def sync_service(
        self,
        repository: ManufacturingRepository,
        gateway: IndustryGateway,
        unit_of_work: UnitOfWork,
        settings: Settings,
    ) -> ManufacturingSyncService:
        return ManufacturingSyncService(
            repository, gateway, unit_of_work, settings.manufacturing_cache_seconds
        )
