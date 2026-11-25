from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.exclusions.repository import ExclusionRepository, SQLExclusionRepository
from app.domains.exclusions.service import ExclusionService


class ExclusionProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def provide_repository(self, session: AsyncSession) -> ExclusionRepository:
        return SQLExclusionRepository(session)

    service = provide(ExclusionService, scope=Scope.REQUEST)
