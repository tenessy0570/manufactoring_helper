from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.exclusions.models import ExclusionList
from app.domains.exclusions.tables import ExclusionsTable


class ExclusionRepository(ABC):
    @abstractmethod
    async def get(self, user_id: UUID) -> ExclusionList: ...
    @abstractmethod
    async def save(self, user_id: UUID, data: ExclusionList) -> None: ...


class SQLExclusionRepository(ExclusionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> ExclusionList:
        row = await self._session.get(ExclusionsTable, user_id)
        return ExclusionList.model_validate({"items": row.items}) if row else ExclusionList()

    async def save(self, user_id: UUID, data: ExclusionList) -> None:
        await self._session.merge(
            ExclusionsTable(user_id=user_id, items=data.model_dump(mode="json")["items"])
        )
        await self._session.flush()
