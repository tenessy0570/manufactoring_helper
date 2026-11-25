from collections.abc import Sequence

from pydantic import BaseModel
from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.orm import Base
from app.core.repository.base import FilterClause, Page, Repository


class SQLAlchemyRepository[TableT: Base, EntityT: BaseModel, ClauseT: FilterClause](
    Repository[EntityT, ClauseT]
):
    """Generic async repository. Subclasses set `table` and `entity` and may extend `_conditions`.

    Table columns must match the entity's field names. Repositories only flush; committing is
    the responsibility of the UnitOfWork that the calling service owns.
    """

    table: type[TableT]
    entity: type[EntityT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, entity_id: object) -> EntityT | None:
        row = await self._session.get(self.table, entity_id)
        return None if row is None else self._map_to_entity(row)

    async def find(self, clause: ClauseT | None = None, page: Page | None = None) -> list[EntityT]:
        statement = select(self.table).where(*self._build_conditions(clause))
        if page is not None:
            statement = statement.limit(page.limit).offset(page.offset)
        rows = await self._session.scalars(statement)
        return [self._map_to_entity(row) for row in rows]

    async def count(self, clause: ClauseT | None = None) -> int:
        statement = (
            select(func.count()).select_from(self.table).where(*self._build_conditions(clause))
        )
        return await self._session.scalar(statement) or 0

    async def add(self, entity: EntityT) -> EntityT:
        row = self.table(**entity.model_dump())
        self._session.add(row)
        await self._session.flush()
        return self._map_to_entity(row)

    async def add_many(self, entities: Sequence[EntityT]) -> None:
        self._session.add_all(self.table(**entity.model_dump()) for entity in entities)
        await self._session.flush()

    async def delete(self, entity_id: object) -> bool:
        row = await self._session.get(self.table, entity_id)
        if row is None:
            return False
        await self._session.delete(row)
        await self._session.flush()
        return True

    def _build_conditions(self, clause: ClauseT | None) -> list[ColumnElement[bool]]:
        if clause is None:
            return []
        return [
            getattr(self.table, name) == value
            for name in type(clause).model_fields
            if (value := getattr(clause, name)) is not None
        ]

    def _map_to_entity(self, row: TableT) -> EntityT:
        return self.entity.model_validate(row, from_attributes=True)
