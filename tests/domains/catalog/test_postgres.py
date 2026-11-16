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
from tests.domains.catalog.test_catalog import NOW, item


@pytest.mark.skipif(os.environ.get("RUN_POSTGRES_TESTS") != "1", reason="Requires Docker")
async def test_migration_and_upsert_on_postgres() -> None:
    migration = runpy.run_path(str(Path("alembic/versions/0001_catalog.py")))

    def upgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
        assert "item_types" in inspect(connection).get_table_names()

    def downgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
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
            async with engine.begin() as connection:
                await connection.run_sync(downgrade)
        finally:
            await engine.dispose()
