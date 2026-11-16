from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.orm import Base
from app.core.repository import FilterClause, SQLAlchemyRepository


class ItemTable(Base):
    __tablename__ = "test_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    category: Mapped[str | None]


class Item(BaseModel):
    id: int
    name: str
    category: str | None = None


class ItemClause(FilterClause):
    name: str | None = None
    category: str | None = None


class ItemRepository(SQLAlchemyRepository[ItemTable, Item, ItemClause]):
    table = ItemTable
    entity = Item


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def session(session_factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


@pytest.fixture
def repository(session: AsyncSession) -> ItemRepository:
    return ItemRepository(session)
