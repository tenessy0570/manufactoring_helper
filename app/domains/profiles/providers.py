from dishka import Provider, Scope, provide
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.profile_calculation import ProfileCalculationService
from app.core.repository import UnitOfWork
from app.domains.profiles.repository import ProfileRepository, SQLProfileRepository
from app.domains.profiles.service import ProfileService


class ProfileProvider(Provider):
    @provide(scope=Scope.REQUEST)
    def repository(self, session: AsyncSession) -> ProfileRepository:
        return SQLProfileRepository(session)

    @provide(scope=Scope.REQUEST)
    def service(self, repository: ProfileRepository, unit_of_work: UnitOfWork) -> ProfileService:
        return ProfileService(repository, unit_of_work)

    calculation = provide(ProfileCalculationService, scope=Scope.REQUEST)
