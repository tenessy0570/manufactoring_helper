from datetime import timedelta

import httpx
from dishka import Provider, Scope, make_async_container
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.orm import Base
from app.domains.health.repository import SQLProgressRepository
from app.domains.health.service import ProgressService
from app.domains.invention.repository import SQLInventionRepository
from app.domains.manufacturing.repository import SQLManufacturingRepository
from app.domains.market.quotes import SQLMarketQuoteReader
from app.main import create_app
from tests.domains.catalog.test_catalog import NOW
from tests.domains.invention.test_invention import request
from tests.domains.manufacturing.test_manufacturing import recipe_state, seed
from tests.helpers import make_settings


async def test_progress_persists_coverage_and_validates_hub() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        repository = SQLProgressRepository(session)
        empty = await repository.snapshot("jita")
        assert empty.catalog_items == 0
        assert empty.market_updated_at is None
        assert all(
            source.status == "missing"
            for source in (await repository.freshness("jita", NOW)).sources
        )
        await seed(session)
        invention = SQLInventionRepository(session)
        await invention.save_request(request())
        saved = await repository.snapshot("jita")
        assert saved.catalog_items == 5
        assert saved.recipes_loaded == 3
        assert saved.recipes_unavailable == 1
        assert saved.history_loaded == 1
        assert saved.invention_ready == 1
        assert saved.market_updated_at is not None
        assert (await repository.snapshot("hek")).history_loaded == 0
        freshness = await repository.freshness("jita", NOW)
        assert [source.source for source in freshness.sources] == [
            "market",
            "history",
            "recipes",
            "invention",
        ]
        assert all(source.status == "fresh" for source in freshness.sources)
        await SQLManufacturingRepository(session, SQLMarketQuoteReader(session)).save(
            recipe_state(expires_at=NOW)
        )
        partial = await repository.freshness("jita", NOW)
        recipes = next(source for source in partial.sources if source.source == "recipes")
        assert recipes.status == "partial"
        assert recipes.fresh == recipes.cached - 1
        assert all(
            source.status == "stale"
            for source in (await repository.freshness("jita", NOW + timedelta(days=2))).sources
        )
        assert (
            next(
                source
                for source in (await repository.freshness("hek", NOW)).sources
                if source.source == "market"
            ).status
            == "missing"
        )
        service = ProgressService(repository)
        provider = Provider(scope=Scope.REQUEST)
        provider.provide(lambda: service, provides=ProgressService)
        container = make_async_container(provider)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(
                create_app(container, make_settings(), require_login=False)
            ),
            base_url="http://test",
        ) as client:
            assert (await client.get("/health/data-progress")).json()["recipes_loaded"] == 3
            assert (await client.get("/health/data-progress?hub=unknown")).status_code == 422
            report = await client.get("/health/freshness?hub=jita")
            assert report.status_code == 200
            assert report.json()["hub_id"] == "jita"
            assert len(report.json()["sources"]) == 4
            assert (await client.get("/health/freshness?hub=unknown")).status_code == 422
        await container.close()
    await engine.dispose()
