import runpy

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect


def test_catalog_migration_upgrades_and_downgrades() -> None:
    migration = runpy.run_path("alembic/versions/0001_catalog.py")
    engine = create_engine("sqlite:///:memory:")
    with (
        engine.begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration["upgrade"]()
        columns = {column["name"] for column in inspect(connection).get_columns("item_types")}
        assert {"type_id", "group_path", "meta_group_id", "is_active"} <= columns
        assert len(inspect(connection).get_indexes("item_types")) == 7
        migration["downgrade"]()
        assert "item_types" not in inspect(connection).get_table_names()
    engine.dispose()
