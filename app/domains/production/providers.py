from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.production.repository import ProductionRepository, SQLProductionRepository
from app.domains.production.service import ProductionEstimateService, ProductionService


class ProductionProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def repository(self, session: AsyncSession) -> ProductionRepository:
        return SQLProductionRepository(session)

    service = provide(ProductionService, scope=Scope.REQUEST)
    estimate = provide(ProductionEstimateService, scope=Scope.REQUEST)
