from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RefreshPolicy, Settings
from app.core.repository import UnitOfWork
from app.domains.market.gateway import EsiMarketGateway, MarketGateway
from app.domains.market.quotes import MarketQuoteReader, SQLMarketQuoteReader
from app.domains.market.repository import MarketRepository, SQLMarketRepository
from app.domains.market.service import MarketService, MarketSyncService
from app.infrastructure.esi import EsiClient


class MarketProvider(Provider):
    quotes = provide(SQLMarketQuoteReader, provides=MarketQuoteReader, scope=Scope.REQUEST)

    @provide(scope=Scope.APP)
    def gateway(self, esi: EsiClient, settings: Settings) -> MarketGateway:
        return EsiMarketGateway(esi, settings.market_cache_seconds)

    @provide(scope=Scope.REQUEST)
    def repository(self, session: AsyncSession, refresh_policy: RefreshPolicy) -> MarketRepository:
        return SQLMarketRepository(session, refresh_policy)

    service = provide(MarketService, scope=Scope.REQUEST)

    @provide(scope=Scope.REQUEST)
    def sync_service(
        self,
        repository: MarketRepository,
        gateway: MarketGateway,
        unit_of_work: UnitOfWork,
        refresh_policy: RefreshPolicy,
    ) -> MarketSyncService:
        return MarketSyncService(repository, gateway, unit_of_work, refresh_policy=refresh_policy)
