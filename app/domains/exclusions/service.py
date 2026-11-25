from uuid import UUID

from app.core.repository import UnitOfWork
from app.domains.exclusions.models import ExclusionList
from app.domains.exclusions.repository import ExclusionRepository


class ExclusionService:
    def __init__(self, repository: ExclusionRepository, unit_of_work: UnitOfWork) -> None:
        self._repository, self._unit_of_work = repository, unit_of_work

    async def get(self, user_id: UUID) -> ExclusionList:
        return await self._repository.get(user_id)

    async def save(self, user_id: UUID, data: ExclusionList) -> ExclusionList:
        data = ExclusionList(items=list({item.type_id: item for item in data.items}.values()))
        try:
            await self._repository.save(user_id, data)
            await self._unit_of_work.commit()
        except BaseException:
            await self._unit_of_work.rollback()
            raise
        return data
