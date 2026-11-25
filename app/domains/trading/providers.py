from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cache import Cache, CacheService
from app.core.config import RefreshPolicy, Settings
from app.core.repository import UnitOfWork
from app.domains.catalog.names import ItemNameService
from app.domains.trading.cargo import CargoService
from app.domains.trading.gateway import EverefTradingGateway, TradingGateway
from app.domains.trading.repository import SQLTradingRepository, TradingRepository
from app.domains.trading.routes import EsiRouteGateway, RouteGateway, TradingRoutes
from app.domains.trading.service import TradingMetadataService, TradingService


class TradingProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_repository(self, session: AsyncSession) -> TradingRepository:
        return SQLTradingRepository(session)

    cargo = provide(CargoService, scope=Scope.REQUEST)

    gateway = provide(EverefTradingGateway, provides=TradingGateway, scope=Scope.APP)

    route_gateway = provide(EsiRouteGateway, provides=RouteGateway, scope=Scope.APP)

    @provide(scope=Scope.APP)
    def provide_route_service(
        self, cache: Cache, loader: CacheService, gateway: RouteGateway, settings: Settings
    ) -> TradingRoutes:
        return TradingRoutes(
            cache, loader, gateway, settings.route_cache_seconds, settings.route_error_cache_seconds
        )

    @provide(scope=Scope.REQUEST)
    def provide_service(
        self,
        repository: TradingRepository,
        names: ItemNameService,
        routes: TradingRoutes,
        refresh_policy: RefreshPolicy,
    ) -> TradingService:
        return TradingService(repository, names, routes=routes, refresh_policy=refresh_policy)

    @provide(scope=Scope.REQUEST)
    def provide_metadata_service(
        self,
        repository: TradingRepository,
        gateway: TradingGateway,
        unit_of_work: UnitOfWork,
        refresh_policy: RefreshPolicy,
    ) -> TradingMetadataService:
        return TradingMetadataService(
            repository, gateway, unit_of_work, refresh_policy=refresh_policy
        )
