import os
import runpy
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from sqlalchemy.engine import URL, Connection
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from app.domains.catalog.repository import SQLItemTypeRepository
from app.domains.history.models import LiquidityQuery
from app.domains.history.repository import SQLHistoryRepository
from app.domains.market.models import PriceQuery
from app.domains.market.repository import SQLMarketRepository
from tests.domains.catalog.test_catalog import NOW, item
from tests.domains.history.test_history import day
from tests.domains.history.test_history import state as history_state
from tests.domains.market.test_market import price, state


@pytest.mark.skipif(os.environ.get("RUN_POSTGRES_TESTS") != "1", reason="Requires Docker")
async def test_migration_and_upsert_on_postgres() -> None:
    migration = runpy.run_path(str(Path("alembic/versions/0001_catalog.py")))
    market_migration = runpy.run_path("alembic/versions/0002_market.py")
    history_migration = runpy.run_path("alembic/versions/0003_history.py")

    def upgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
            market_migration["upgrade"]()
            history_migration["upgrade"]()
        assert "item_types" in inspect(connection).get_table_names()

    def downgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            history_migration["downgrade"]()
            market_migration["downgrade"]()
            migration["downgrade"]()
        assert "item_types" not in inspect(connection).get_table_names()

    with (
        DockerContainer("postgres:17")
        .with_env("POSTGRES_USER", "catalog_test")
        .with_env("POSTGRES_PASSWORD", "catalog_test")
        .with_env("POSTGRES_DB", "catalog_test")
        .with_exposed_ports(5432)
        .waiting_for(LogMessageWaitStrategy("listening on IPv4 address"))
    ) as postgres:
        host = postgres.get_container_host_ip()
        engine = create_async_engine(
            URL.create(
                "postgresql+asyncpg",
                username="catalog_test",
                password="catalog_test",
                host="127.0.0.1" if host == "localhost" else host,
                port=int(postgres.get_exposed_port(5432)),
                database="catalog_test",
            ),
            connect_args={"ssl": False},
        )
        try:
            async with engine.begin() as connection:
                await connection.run_sync(upgrade)
            async with AsyncSession(engine) as session:
                repository = SQLItemTypeRepository(session)
                await repository.upsert_many([item(number) for number in range(205)])
                await repository.upsert_many([item(10, name="Updated")])
                await session.commit()
                assert await repository.count() == 205
                stored = await repository.get(10)
                assert stored is not None
                assert stored.name == "Updated"
                assert await repository.latest_synced_at() == NOW
                market = SQLMarketRepository(session)
                await market.replace(state(), [price()])
                await market.replace(state("amarr"), [price(hub_id="amarr")])
                await session.commit()
                assert await market.state("jita") == state()
                await market.replace(state(items=205), [price(number) for number in range(205)])
                await session.commit()
                assert await market.count(PriceQuery(), NOW) == 205
                history = SQLHistoryRepository(session)
                await history.replace(history_state(), [day(), day(2)])
                await history.replace(history_state(region=10000043), [day(volume=100)])
                await session.commit()
                assert await history.state(10000002, 10) == history_state()
                values, total = await history.liquidity(LiquidityQuery(days=2, type_ids=[10]), NOW)
                assert total == 1
                assert values[0].daily_isk_volume == 205
                values, _ = await history.liquidity(
                    LiquidityQuery(hub_id="amarr", days=2, type_ids=[10]), NOW
                )
                assert values[0].daily_units == 50
                await history.replace(history_state(), [])
                await session.rollback()
                values, _ = await history.liquidity(LiquidityQuery(days=2, type_ids=[10]), NOW)
                assert values[0].data_days == 2
                assert await market.count(PriceQuery(hub_id="amarr"), NOW) == 1
                stored_price = (await market.find(PriceQuery(type_ids=[10]), NOW))[0]
                assert stored_price.buy_price == price().buy_price
                await market.replace(state(items=0), [])
                await session.rollback()
                assert await market.count(PriceQuery(), NOW) == 205
            async with engine.begin() as connection:
                await connection.run_sync(downgrade)
        finally:
            await engine.dispose()
