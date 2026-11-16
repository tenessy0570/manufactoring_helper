from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.repository import UnitOfWork
from app.domains.history.gateway import EsiHistoryGateway, HistoryGateway
from app.domains.history.repository import HistoryRepository, SQLHistoryRepository
from app.domains.history.service import HistoryService, HistorySyncService
from app.infrastructure.esi import EsiClient


class HistoryProvider(Provider):
    @provide(scope=Scope.APP)
    def gateway(self, esi: EsiClient, settings: Settings) -> HistoryGateway:
        return EsiHistoryGateway(esi, settings.history_cache_seconds)

    @provide(scope=Scope.REQUEST)
    def repository(self, session: AsyncSession) -> HistoryRepository:
        return SQLHistoryRepository(session)

    @provide(scope=Scope.REQUEST)
    def service(self, repository: HistoryRepository) -> HistoryService:
        return HistoryService(repository)

    @provide(scope=Scope.REQUEST)
    def sync_service(
        self, repository: HistoryRepository, gateway: HistoryGateway, unit_of_work: UnitOfWork
    ) -> HistorySyncService:
        return HistorySyncService(repository, gateway, unit_of_work)
