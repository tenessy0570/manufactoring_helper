from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.repository import UnitOfWork
from app.domains.catalog.names import ItemNameService
from app.domains.trading.cargo import CargoService
from app.domains.trading.gateway import EverefTradingGateway, TradingGateway
from app.domains.trading.repository import SQLTradingRepository, TradingRepository
from app.domains.trading.routes import EsiRouteGateway, RouteGateway, TradingRoutes
from app.domains.trading.service import TradingMetadataService, TradingService


class TradingProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def repository(self, session: AsyncSession) -> TradingRepository:
        return SQLTradingRepository(session)

    cargo = provide(CargoService, scope=Scope.REQUEST)

    gateway = provide(EverefTradingGateway, provides=TradingGateway, scope=Scope.APP)

    route_gateway = provide(EsiRouteGateway, provides=RouteGateway, scope=Scope.APP)
    routes = provide(TradingRoutes, scope=Scope.APP)

    @provide(scope=Scope.REQUEST)
    def service(
        self, repository: TradingRepository, names: ItemNameService, routes: TradingRoutes
    ) -> TradingService:
        return TradingService(repository, names, routes=routes)

    @provide(scope=Scope.REQUEST)
    def metadata(
        self, repository: TradingRepository, gateway: TradingGateway, unit_of_work: UnitOfWork
    ) -> TradingMetadataService:
        return TradingMetadataService(repository, gateway, unit_of_work)
