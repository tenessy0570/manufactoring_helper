import json
from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import DEFAULT_REFRESH
from app.core.orm import Base
from app.core.repository import SQLAlchemyUnitOfWork
from app.domains.health.repository import SQLProgressRepository
from app.domains.history.repository import SQLHistoryRepository
from app.domains.manufacturing.models import ManufacturingQuery
from app.domains.manufacturing.service import ManufacturingService
from app.domains.market.models import PriceQuery
from app.domains.market.repository import SQLMarketRepository
from app.domains.market.service import MarketSyncService
from app.domains.trading.calculation import calculate_trade
from app.domains.trading.models import TradingQuery
from app.main import create_app
from tests.domains.catalog.test_catalog import NOW
from tests.domains.manufacturing.test_manufacturing import seed
from tests.domains.market.test_market import FakeGateway
from tests.domains.trading.test_trading import trade
from tests.helpers import make_settings


async def test_configured_market_interval_agrees_across_worker_results_and_header() -> None:
    policy = make_settings(market_refresh_seconds=60).refresh_policy
    now = NOW + timedelta(minutes=10)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        manufacturing = await seed(session)
        market = SQLMarketRepository(session, policy)
        assert await SQLMarketRepository(session).find(PriceQuery(fresh_only=True), now)
        assert not await market.find(PriceQuery(fresh_only=True), now)

        service = ManufacturingService(
            manufacturing,
            SQLHistoryRepository(session, policy),
            lambda: now,
            refresh_policy=policy,
        )
        page = await service.opportunities(ManufacturingQuery(type_ids=[10]))
        assert page.items
        assert page.items[0].stale
        assert all(
            page.items[0].freshness_deadlines[key] <= now
            for key in ("product_market", "material_market")
        )
        assert not (
            await service.opportunities(ManufacturingQuery(type_ids=[10], fresh_only=True))
        ).items
        header = await SQLProgressRepository(session, policy).freshness("jita", now)
        assert next(s for s in header.sources if s.source == "market").status == "stale"

        gateway = FakeGateway()
        uow = SQLAlchemyUnitOfWork(session)
        default_worker = MarketSyncService(market, gateway, uow, lambda: now)
        assert (await default_worker.sync_if_stale("jita")).skipped
        worker = MarketSyncService(market, gateway, uow, lambda: now, policy)
        assert not (await worker.sync_if_stale("jita")).skipped
        assert gateway.calls
    await engine.dispose()

    app = create_app(settings=make_settings(market_refresh_seconds=60))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app), base_url="http://test"
    ) as client:
        response = await client.get("/ui/config.js")
        payload = response.text.removeprefix("window.eveConfig = Object.freeze(").removesuffix(");")
        assert json.loads(payload)["marketFreshnessMs"] == 60000

    data, query = trade(), TradingQuery()
    assert calculate_trade(data, query, now) is not None
    assert calculate_trade(data, TradingQuery(fresh_only=True), now, policy) is None


async def test_history_interval_changes_due_selection_and_header_together() -> None:
    policy = make_settings(history_cache_seconds=7200).refresh_policy
    now = NOW + timedelta(hours=3)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with AsyncSession(engine) as session:
        await seed(session)
        repository = SQLHistoryRepository(session, policy)
        saved = await repository.state(10000002, 10)
        assert saved is not None
        saved.expires_at = NOW
        await repository.replace(saved, [])
        assert not await SQLHistoryRepository(session).due(10000002, [10], now)
        assert await repository.due(10000002, [10], now) == {10}
        header = await SQLProgressRepository(session, policy).freshness("jita", now)
        assert next(s for s in header.sources if s.source == "history").status == "stale"
    await engine.dispose()
    assert DEFAULT_REFRESH.history_seconds == 86400
