from abc import abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app.core.repository import Page, Repository, SQLAlchemyRepository
from app.domains.catalog.models import ItemType, ItemTypeClause
from app.domains.catalog.tables import ItemTypeTable


class ItemTypeRepository(Repository[ItemType, ItemTypeClause]):
    @abstractmethod
    async def upsert_many(self, entities: Sequence[ItemType]) -> None: ...

    @abstractmethod
    async def deactivate_before(self, synced_at: datetime) -> None: ...

    @abstractmethod
    async def latest_synced_at(self) -> datetime | None: ...


class SQLItemTypeRepository(
    SQLAlchemyRepository[ItemTypeTable, ItemType, ItemTypeClause], ItemTypeRepository
):
    table = ItemTypeTable
    entity = ItemType

    async def find(
        self, clause: ItemTypeClause | None = None, page: Page | None = None
    ) -> list[ItemType]:
        statement = select(self.table).where(*self._conditions(clause)).order_by(self.table.type_id)
        if page is not None:
            statement = statement.limit(page.limit).offset(page.offset)
        return [self._to_entity(row) for row in await self._session.scalars(statement)]

    def _conditions(self, clause: ItemTypeClause | None) -> list[ColumnElement[bool]]:
        clause = clause or ItemTypeClause()
        conditions: list[ColumnElement[bool]] = []
        if clause.search is not None:
            conditions.append(self.table.name.icontains(clause.search, autoescape=True))
        for field, values in (
            (self.table.type_id, clause.type_ids),
            (self.table.category, clause.categories),
            (self.table.market_group_id, clause.market_group_ids),
            (self.table.meta_group_id, clause.meta_group_ids),
        ):
            if values is not None:
                conditions.append(field.in_(values))
        if clause.exclude_type_ids is not None:
            conditions.append(self.table.type_id.not_in(clause.exclude_type_ids))
        for column, value in (
            (self.table.is_rig, clause.is_rig),
            (self.table.is_active, clause.is_active),
        ):
            if value is not None:
                conditions.append(column == value)
        if clause.has_meta_group is not None:
            conditions.append(
                self.table.meta_group_id.is_not(None)
                if clause.has_meta_group
                else self.table.meta_group_id.is_(None)
            )
        return conditions

    async def upsert_many(self, entities: Sequence[ItemType]) -> None:
        dialect = self._session.get_bind().dialect.name
        insert = pg_insert if dialect == "postgresql" else sqlite_insert
        # Keep well below both asyncpg and SQLite parameter limits.
        for start in range(0, len(entities), 100):
            statement = insert(self.table).values(
                [entity.model_dump() for entity in entities[start : start + 100]]
            )
            statement = statement.on_conflict_do_update(
                index_elements=[self.table.type_id],
                set_={
                    column.name: getattr(statement.excluded, column.name)
                    for column in self.table.__table__.columns
                    if column.name != "type_id"
                },
            )
            await self._session.execute(statement)

    async def deactivate_before(self, synced_at: datetime) -> None:
        await self._session.execute(
            update(self.table).where(self.table.synced_at < synced_at).values(is_active=False)
        )

    async def latest_synced_at(self) -> datetime | None:
        result = await self._session.scalar(select(func.max(self.table.synced_at)))
        return (
            None
            if result is None
            else result.replace(tzinfo=UTC)
            if result.tzinfo is None
            else result
        )
