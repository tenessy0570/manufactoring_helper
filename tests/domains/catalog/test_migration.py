import runpy

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_catalog_migration_upgrades_and_downgrades() -> None:
    migration = runpy.run_path("alembic/versions/0001_catalog.py")
    market = runpy.run_path("alembic/versions/0002_market.py")
    history = runpy.run_path("alembic/versions/0003_history.py")
    manufacturing = runpy.run_path("alembic/versions/0004_manufacturing.py")
    counts = runpy.run_path("alembic/versions/0005_order_counts.py")
    invention = runpy.run_path("alembic/versions/0006_invention.py")
    profiles = runpy.run_path("alembic/versions/0007_profiles.py")
    depth = runpy.run_path("alembic/versions/0008_buy_price_levels.py")

    untaxed = runpy.run_path("alembic/versions/0009_tax_free_invention.py")

    accounts = runpy.run_path("alembic/versions/0010_accounts.py")

    production = runpy.run_path("alembic/versions/0011_production_history.py")

    engine = create_engine("sqlite:///:memory:")
    with (
        engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration["upgrade"]()
        market["upgrade"]()
        history["upgrade"]()
        manufacturing["upgrade"]()
        counts["upgrade"]()
        invention["upgrade"]()
        profiles["upgrade"]()
        depth["upgrade"]()
        untaxed["upgrade"]()
        accounts["upgrade"]()
        production["upgrade"]()
        assert "productions" in inspect(connection).get_table_names()
        columns = {column["name"] for column in inspect(connection).get_columns("item_types")}
        assert {"type_id", "group_path", "meta_group_id", "is_active"} <= columns
        assert len(inspect(connection).get_indexes("item_types")) == 7
        assert "market_prices" in inspect(connection).get_table_names()
        assert "market_history" in inspect(connection).get_table_names()
        assert "manufacturing_recipes" in inspect(connection).get_table_names()
        assert "invention_plans" in inspect(connection).get_table_names()
        assert "profiles" in inspect(connection).get_table_names()
        production["downgrade"]()
        accounts["downgrade"]()
        untaxed["downgrade"]()
        depth["downgrade"]()
        profiles["downgrade"]()
        invention["downgrade"]()
        counts["downgrade"]()
        manufacturing["downgrade"]()
        history["downgrade"]()
        market["downgrade"]()
        assert "market_prices" not in inspect(connection).get_table_names()
        migration["downgrade"]()
        assert "item_types" not in inspect(connection).get_table_names()
    engine.dispose()
