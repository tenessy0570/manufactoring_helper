from app.core.database import create_engine, create_session_factory
from tests.helpers import make_settings


async def test_create_engine_targets_configured_database() -> None:
    engine = create_engine(make_settings(postgres_db="eve_test"))

    assert engine.url.database == "eve_test"
    assert engine.url.drivername == "postgresql+asyncpg"
    await engine.dispose()


async def test_session_factory_keeps_objects_usable_after_commit() -> None:
    engine = create_engine(make_settings())
    factory = create_session_factory(engine)

    async with factory() as session:
        assert session.sync_session.expire_on_commit is False
    await engine.dispose()
