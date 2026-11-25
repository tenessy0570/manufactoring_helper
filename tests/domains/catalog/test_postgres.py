import asyncio
import os
import runpy
from datetime import timedelta
from pathlib import Path
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from sqlalchemy.engine import URL, Connection
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import LogMessageWaitStrategy

from app.core.repository import SQLAlchemyUnitOfWork
from app.domains.catalog.repository import SQLItemTypeRepository
from app.domains.history.models import LiquidityQuery
from app.domains.history.repository import SQLHistoryRepository
from app.domains.invention.models import PlanState
from app.domains.invention.repository import SQLInventionRepository
from app.domains.manufacturing.models import ManufacturingQuery
from app.domains.manufacturing.repository import SQLManufacturingRepository
from app.domains.manufacturing.service import ManufacturingService
from app.domains.market.models import PriceQuery
from app.domains.market.quotes import SQLMarketQuoteReader
from app.domains.market.repository import SQLMarketRepository
from app.domains.profiles.models import ProfileCreate, ProfileSettings
from app.domains.profiles.repository import SQLProfileRepository
from app.domains.profiles.service import ProfileService
from tests.domains.catalog.test_catalog import NOW, item
from tests.domains.history.test_history import day
from tests.domains.history.test_history import get_state as history_state
from tests.domains.invention.test_invention import get_plan, request, settings
from tests.domains.manufacturing.test_manufacturing import recipe_state
from tests.domains.market.test_market import get_state, price


@pytest.mark.skipif(os.environ.get("RUN_POSTGRES_TESTS") != "1", reason="Requires Docker")
async def test_migration_and_upsert_on_postgres() -> None:
    migration = runpy.run_path(str(Path("alembic/versions/0001_catalog.py")))
    market_migration = runpy.run_path("alembic/versions/0002_market.py")
    history_migration = runpy.run_path("alembic/versions/0003_history.py")
    manufacturing_migration = runpy.run_path("alembic/versions/0004_manufacturing.py")
    counts_migration = runpy.run_path("alembic/versions/0005_order_counts.py")
    invention_migration = runpy.run_path("alembic/versions/0006_invention.py")
    profile_migration = runpy.run_path("alembic/versions/0007_profiles.py")

    depth_migration = runpy.run_path("alembic/versions/0008_buy_price_levels.py")

    untaxed_migration = runpy.run_path("alembic/versions/0009_tax_free_invention.py")

    account_migration = runpy.run_path("alembic/versions/0010_accounts.py")

    production_migration = runpy.run_path("alembic/versions/0011_production_history.py")

    def upgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            migration["upgrade"]()
            market_migration["upgrade"]()
            history_migration["upgrade"]()
            manufacturing_migration["upgrade"]()
            counts_migration["upgrade"]()
            invention_migration["upgrade"]()
            profile_migration["upgrade"]()
            depth_migration["upgrade"]()
            untaxed_migration["upgrade"]()
            account_migration["upgrade"]()
            production_migration["upgrade"]()
        assert "item_types" in inspect(connection).get_table_names()

    def downgrade(connection: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection)):
            production_migration["downgrade"]()
            account_migration["downgrade"]()
            untaxed_migration["downgrade"]()
            depth_migration["downgrade"]()
            profile_migration["downgrade"]()
            invention_migration["downgrade"]()
            counts_migration["downgrade"]()
            manufacturing_migration["downgrade"]()
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
                assert await repository.get_latest_sync_time() == NOW
                market = SQLMarketRepository(session)
                await market.replace(
                    get_state(),
                    [price(buy_levels=[{"price": "9.10", "volume": 10, "order_count": 1}])],
                )
                assert (await market.find(PriceQuery(), NOW))[0].buy_levels is not None
                await market.replace(get_state("amarr"), [price(hub_id="amarr")])
                await session.commit()
                assert await market.get_state("jita") == get_state()
                await market.replace(get_state(items=205), [price(number) for number in range(205)])
                await session.commit()
                assert await market.count(PriceQuery(), NOW) == 205
                history = SQLHistoryRepository(session)
                await history.replace(history_state(), [day(), day(2)])
                await history.replace(history_state(region=10000043), [day(volume=100)])
                await session.commit()
                assert await history.get_state(10000002, 10) == history_state()
                assert await history.find_due_type_ids(
                    10000002, [10, 999], NOW + timedelta(hours=23)
                ) == {999}
                assert await history.find_due_type_ids(10000002, [10], NOW + timedelta(days=1)) == {
                    10
                }
                values, total = await history.get_liquidity(
                    LiquidityQuery(days=2, type_ids=[10]), NOW
                )
                assert total == 1
                assert values[0].daily_isk_volume == 205
                values, _ = await history.get_liquidity(
                    LiquidityQuery(hub_id="amarr", days=2, type_ids=[10]), NOW
                )
                assert values[0].daily_units == 50
                await history.replace(history_state(), [])
                await session.rollback()
                values, _ = await history.get_liquidity(LiquidityQuery(days=2, type_ids=[10]), NOW)
                assert values[0].data_days == 2
                manufacturing = SQLManufacturingRepository(session, SQLMarketQuoteReader(session))
                await manufacturing.save(recipe_state())
                await session.commit()
                assert (await manufacturing.get_recipes([10]))[10] == recipe_state()
                service = ManufacturingService(manufacturing, history, lambda: NOW)
                page = await service.get_opportunities(ManufacturingQuery(type_ids=[10]))
                assert page.total == 1
                assert str(page.items[0].profit_per_unit) == "-42.40"
                await manufacturing.save(recipe_state(recipe=None))
                await session.rollback()
                assert (await manufacturing.get_recipes([10]))[10].recipe is not None
                invention = SQLInventionRepository(session)
                plans = PlanState(
                    key=settings().plan_key,
                    plans=[get_plan()],
                    synced_at=NOW,
                    expires_at=NOW + timedelta(days=7),
                )
                await invention.save_plan(plans)
                await invention.ensure_request(request(status="pending", result=None))
                await invention.save_request(request())
                await invention.ensure_request(request(status="pending", result=None))
                await session.commit()
                assert await invention.get_cached_plan(settings().plan_key) == plans
                assert (await invention.get_requests([settings().key]))[settings().key] == request()
                from app.domains.accounts.models import Credentials, UserCreate
                from app.domains.accounts.repository import SQLAccountRepository
                from app.domains.accounts.service import AccountService
                from tests.domains.accounts.test_accounts import PASSWORD, Limiter

                accounts = AccountService(
                    SQLAccountRepository(session), SQLAlchemyUnitOfWork(session), Limiter()
                )
                account = await accounts.create(
                    UserCreate.model_validate(
                        {"username": "postgres_admin", "password": PASSWORD, "is_superuser": True}
                    )
                )
                identity, token = await accounts.login(
                    Credentials.model_validate(
                        {"username": "postgres_admin", "password": PASSWORD}
                    ),
                    "test",
                )
                assert identity.id == account.id
                assert await accounts.get_session_user(token) == identity
                await accounts.logout(token)
                assert await accounts.get_session_user(token) is None
                from decimal import Decimal

                from app.domains.production.models import EntryInput, ProductionCreate
                from app.domains.production.repository import SQLProductionRepository
                from app.domains.production.service import ProductionService

                productions = ProductionService(
                    SQLProductionRepository(session), repository, SQLAlchemyUnitOfWork(session)
                )
                batch = await productions.create(account.id, ProductionCreate(type_id=10))

                async def add_income(amount: int) -> None:
                    async with AsyncSession(engine) as other:
                        service = ProductionService(
                            SQLProductionRepository(other),
                            SQLItemTypeRepository(other),
                            SQLAlchemyUnitOfWork(other),
                        )
                        await service.save_entry(
                            account.id, batch.id, EntryInput(kind="income", amount=Decimal(amount))
                        )

                await asyncio.gather(add_income(10), add_income(20))
                stored_batch = await productions.get(account.id, batch.id)
                assert stored_batch.totals["income"] == 30
                assert len(stored_batch.entries) == 2
                await productions.delete(account.id, batch.id)
                profiles = ProfileService(
                    SQLProfileRepository(session), SQLAlchemyUnitOfWork(session)
                )
                default_profile = await profiles.get()
                assert default_profile.settings == ProfileSettings()
                first_profile = await profiles.create(ProfileCreate(name="First"))
                second_profile = await profiles.create(
                    ProfileCreate(name="Second", settings=ProfileSettings(hub_id="amarr"))
                )

                async def select_profile(profile_id: UUID) -> None:
                    async with AsyncSession(engine) as other:
                        service = ProfileService(
                            SQLProfileRepository(other), SQLAlchemyUnitOfWork(other)
                        )
                        await service.set_default(profile_id)

                await asyncio.gather(
                    select_profile(first_profile.id), select_profile(second_profile.id)
                )
                profile_page = await profiles.find()
                assert sum(profile.is_default for profile in profile_page.items) == 1
                assert profile_page.default_profile_id in (first_profile.id, second_profile.id)
                await session.rollback()
                await profiles.delete(profile_page.default_profile_id)
                assert (await profiles.get()).id == default_profile.id
                assert await market.count(PriceQuery(hub_id="amarr"), NOW) == 1
                stored_price = (await market.find(PriceQuery(type_ids=[10]), NOW))[0]
                assert stored_price.buy_price == price().buy_price
                await market.replace(get_state(items=0), [])
                await session.rollback()
                assert await market.count(PriceQuery(), NOW) == 205
            async with engine.begin() as connection:
                await connection.run_sync(downgrade)
        finally:
            await engine.dispose()
