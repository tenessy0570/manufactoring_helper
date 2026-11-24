from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RefreshPolicy, Settings
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
    def repository(self, session: AsyncSession, refresh_policy: RefreshPolicy) -> HistoryRepository:
        return SQLHistoryRepository(session, refresh_policy)

    @provide(scope=Scope.REQUEST)
    def service(
        self, repository: HistoryRepository, refresh_policy: RefreshPolicy
    ) -> HistoryService:
        return HistoryService(repository, refresh_policy=refresh_policy)

    @provide(scope=Scope.REQUEST)
    def sync_service(
        self,
        repository: HistoryRepository,
        gateway: HistoryGateway,
        unit_of_work: UnitOfWork,
        refresh_policy: RefreshPolicy,
    ) -> HistorySyncService:
        return HistorySyncService(repository, gateway, unit_of_work, refresh_policy=refresh_policy)
