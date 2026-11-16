from collections.abc import AsyncIterator

import httpx
from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.repository import UnitOfWork
from app.domains.catalog.gateway import CatalogGateway, EsiEverefCatalogGateway
from app.domains.catalog.repository import ItemTypeRepository, SQLItemTypeRepository
from app.domains.catalog.selector import MarketTreeSelector
from app.domains.catalog.service import CatalogService, CatalogSyncService
from app.infrastructure.esi import EsiClient
from app.infrastructure.esi.client import make_compatibility_date_provider
from app.infrastructure.everef import EverefClient


class CatalogProvider(Provider):
    @provide(scope=Scope.APP)
    async def esi(self, settings: Settings) -> AsyncIterator[EsiClient]:
        async with httpx.AsyncClient(
            base_url=settings.esi_base_url,
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.esi_user_agent},
        ) as http:
            yield EsiClient(
                http,
                settings.esi_max_concurrency,
                settings.http_max_retries,
                make_compatibility_date_provider(settings.esi_compatibility_date),
            )

    @provide(scope=Scope.APP)
    async def everef(self, settings: Settings) -> AsyncIterator[EverefClient]:
        async with httpx.AsyncClient(
            base_url=settings.everef_base_url,
            timeout=settings.http_timeout_seconds,
            headers={"User-Agent": settings.esi_user_agent},
        ) as http:
            yield EverefClient(http, settings.everef_max_concurrency, settings.http_max_retries)

    @provide(scope=Scope.APP)
    def gateway(self, esi: EsiClient, everef: EverefClient) -> CatalogGateway:
        return EsiEverefCatalogGateway(esi, everef)

    selector = provide(MarketTreeSelector, scope=Scope.APP)

    @provide(scope=Scope.REQUEST)
    def repository(self, session: AsyncSession) -> ItemTypeRepository:
        return SQLItemTypeRepository(session)

    service = provide(CatalogService, scope=Scope.REQUEST)

    @provide(scope=Scope.REQUEST)
    def sync_service(
        self,
        repository: ItemTypeRepository,
        gateway: CatalogGateway,
        unit_of_work: UnitOfWork,
        selector: MarketTreeSelector,
    ) -> CatalogSyncService:
        return CatalogSyncService(repository, gateway, unit_of_work, selector)
