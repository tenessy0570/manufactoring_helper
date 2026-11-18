from abc import ABC, abstractmethod
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.production.models import Production
from app.domains.production.tables import ProductionTable


class ProductionRepository(ABC):
    @abstractmethod
    async def find(self, user_id: UUID, offset: int, limit: int) -> list[Production]: ...

    @abstractmethod
    async def get(
        self, user_id: UUID, production_id: UUID, lock: bool = False
    ) -> Production | None: ...

    @abstractmethod
    async def save(self, production: Production) -> None: ...

    @abstractmethod
    async def delete(self, user_id: UUID, production_id: UUID) -> None: ...


class SQLProductionRepository(ProductionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(self, user_id: UUID, offset: int, limit: int) -> list[Production]:
        rows = await self._session.scalars(
            select(ProductionTable)
            .where(ProductionTable.user_id == user_id)
            .order_by(ProductionTable.created_at.desc(), ProductionTable.id)
            .offset(offset)
            .limit(limit)
        )
        return [Production.model_validate(row, from_attributes=True) for row in rows]

    async def get(
        self, user_id: UUID, production_id: UUID, lock: bool = False
    ) -> Production | None:
        statement = select(ProductionTable).where(
            ProductionTable.id == production_id, ProductionTable.user_id == user_id
        )
        if lock:
            statement = statement.with_for_update().execution_options(populate_existing=True)
        row = await self._session.scalar(statement)
        return None if row is None else Production.model_validate(row, from_attributes=True)

    async def save(self, production: Production) -> None:
        await self._session.merge(
            ProductionTable(
                **production.model_dump(exclude={"entries", "totals"}),
                entries=[entry.model_dump(mode="json") for entry in production.entries],
            )
        )
        await self._session.flush()

    async def delete(self, user_id: UUID, production_id: UUID) -> None:
        row = await self._session.scalar(
            select(ProductionTable).where(
                ProductionTable.id == production_id, ProductionTable.user_id == user_id
            )
        )
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()
