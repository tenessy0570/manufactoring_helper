from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.repository import SQLAlchemyUnitOfWork
from tests.core.repository.conftest import Item, ItemRepository


async def test_commit_makes_changes_visible_to_other_sessions(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await ItemRepository(session).add(Item(id=1, name="rig"))

    await SQLAlchemyUnitOfWork(session).commit()

    async with session_factory() as other_session:
        assert await ItemRepository(other_session).get(1) == Item(id=1, name="rig")


async def test_rollback_discards_changes(
    session: AsyncSession, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await ItemRepository(session).add(Item(id=1, name="rig"))

    await SQLAlchemyUnitOfWork(session).rollback()

    async with session_factory() as other_session:
        assert await ItemRepository(other_session).get(1) is None


async def test_closing_a_session_without_commit_discards_changes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await ItemRepository(session).add(Item(id=1, name="rig"))

    async with session_factory() as other_session:
        assert await ItemRepository(other_session).get(1) is None
