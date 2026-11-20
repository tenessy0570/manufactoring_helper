from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container

from app.core.di import create_container
from app.domains.catalog.gateway import CatalogGateway, EsiEverefCatalogGateway
from app.domains.catalog.models import CatalogSyncReport
from app.domains.catalog.repository import ItemTypeRepository, SQLItemTypeRepository
from app.domains.catalog.service import CatalogService, CatalogSyncService
from app.domains.history.gateway import EsiHistoryGateway, HistoryGateway
from app.domains.history.repository import HistoryRepository, SQLHistoryRepository
from app.domains.history.service import HistoryService, HistorySyncService
from app.domains.invention.gateway import EverefInventionGateway, InventionGateway
from app.domains.invention.queue import InventionQueue, RedisInventionQueue
from app.domains.invention.repository import InventionRepository, SQLInventionRepository
from app.domains.invention.service import InventionService, InventionSyncService
from app.domains.manufacturing.gateway import EverefIndustryGateway, IndustryClient, IndustryGateway
from app.domains.manufacturing.repository import ManufacturingRepository, SQLManufacturingRepository
from app.domains.manufacturing.service import ManufacturingService, ManufacturingSyncService
from app.domains.market.gateway import EsiMarketGateway, MarketGateway
from app.domains.market.models import MarketSyncReport
from app.domains.market.repository import MarketRepository, SQLMarketRepository
from app.domains.market.service import MarketService, MarketSyncService
from app.domains.profiles.repository import ProfileRepository, SQLProfileRepository
from app.domains.profiles.service import ProfileCalculationService, ProfileService
from app.infrastructure.esi import EsiClient
from app.workers import settings as worker
from tests.helpers import make_settings


async def test_catalog_provider_wiring_and_clients_close() -> None:
    container = create_container(make_settings())
    async with container() as scope:
        assert isinstance(await scope.get(CatalogGateway), EsiEverefCatalogGateway)
        assert isinstance(await scope.get(ItemTypeRepository), SQLItemTypeRepository)
        assert isinstance(await scope.get(CatalogService), CatalogService)
        assert isinstance(await scope.get(CatalogSyncService), CatalogSyncService)
        assert isinstance(await scope.get(MarketGateway), EsiMarketGateway)
        assert isinstance(await scope.get(MarketRepository), SQLMarketRepository)
        assert isinstance(await scope.get(MarketService), MarketService)
        assert isinstance(await scope.get(MarketSyncService), MarketSyncService)
        assert isinstance(await scope.get(HistoryGateway), EsiHistoryGateway)
        assert isinstance(await scope.get(HistoryRepository), SQLHistoryRepository)
        assert isinstance(await scope.get(HistoryService), HistoryService)
        assert isinstance(await scope.get(HistorySyncService), HistorySyncService)
        assert isinstance(await scope.get(IndustryGateway), EverefIndustryGateway)
        assert isinstance(await scope.get(ManufacturingRepository), SQLManufacturingRepository)
        assert isinstance(await scope.get(ManufacturingService), ManufacturingService)
        assert isinstance(await scope.get(ManufacturingSyncService), ManufacturingSyncService)
        assert isinstance(await scope.get(InventionGateway), EverefInventionGateway)
        assert isinstance(await scope.get(InventionRepository), SQLInventionRepository)
        assert isinstance(await scope.get(InventionService), InventionService)
        assert isinstance(await scope.get(InventionSyncService), InventionSyncService)
        assert isinstance(await scope.get(InventionQueue), RedisInventionQueue)
        assert isinstance(await scope.get(ProfileRepository), SQLProfileRepository)
        assert isinstance(await scope.get(ProfileService), ProfileService)
        assert isinstance(await scope.get(ProfileCalculationService), ProfileCalculationService)
        industry = await scope.get(IndustryClient)
        esi = await scope.get(EsiClient)
        assert esi._http.headers["User-Agent"] == "eve-manufacturing"
    await container.close()
    assert esi._http.is_closed
    assert industry._http.is_closed


async def test_worker_job_scope_and_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    closed: list[bool] = []
    service = AsyncMock(spec=CatalogSyncService)
    service.sync_if_stale.return_value = CatalogSyncReport(items=42)

    async def scoped_service() -> AsyncIterator[CatalogSyncService]:
        yield service
        closed.append(True)

    provider = Provider(scope=Scope.REQUEST)
    provider.provide(scoped_service, provides=CatalogSyncService)
    container = make_async_container(provider)
    monkeypatch.setattr(worker, "get_settings", lambda: make_settings(catalog_max_age_hours=12))
    monkeypatch.setattr(worker, "create_container", lambda settings: container)
    ctx: dict[str, Any] = {}
    await worker.startup(ctx)
    assert (await worker.sync_catalog(ctx))["items"] == 42
    service.sync_if_stale.assert_awaited_once_with(timedelta(hours=12))
    assert closed == [True]
    await worker.shutdown(ctx)


def test_worker_launch_uses_configured_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = make_settings(redis_host="queue", redis_port=6380)
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    calls: list[dict[str, Any]] = []

    def run(config: dict[str, Any], **kwargs: Any) -> None:
        calls.append({**config, **kwargs})

    monkeypatch.setattr(worker, "run_worker", run)
    worker.main()
    assert calls[0]["redis_settings"].host == "queue"
    assert calls[0]["redis_settings"].port == 6380
    assert calls[0]["max_jobs"] == 1
    assert calls[0]["keep_result"] == 0
    assert calls[0]["cron_jobs"][0].run_at_startup


@pytest.mark.parametrize("fail_jita", [False, True])
async def test_market_worker_isolates_hubs_and_continues_on_failure(fail_jita: bool) -> None:
    service = AsyncMock(spec=MarketSyncService)

    async def sync(hub_id: str) -> MarketSyncReport:
        if fail_jita and hub_id == "jita":
            raise ConnectionError("offline")
        return MarketSyncReport(hub_id=hub_id, items=3)

    service.sync_if_stale.side_effect = sync
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=MarketSyncService)
    container = make_async_container(provider)
    try:
        if fail_jita:
            with pytest.raises(RuntimeError, match="jita"):
                await worker.sync_markets({"container": container})
        else:
            assert len(await worker.sync_markets({"container": container})) == 5
        assert [call.args[0] for call in service.sync_if_stale.await_args_list] == [
            "jita",
            "amarr",
            "dodixie",
            "rens",
            "hek",
        ]
    finally:
        await container.close()


def test_owner_refresh_schedule() -> None:
    jobs = worker.WorkerSettings.cron_jobs
    assert len(jobs) == 5
    for job in jobs:
        assert job.hour is None
        assert job.minute == set(range(60))
        assert job.run_at_startup
        assert job.keep_result_s == 0
    assert len({job.job_id for job in jobs}) == 5


async def test_hub_retry_delay_does_not_block_other_markets() -> None:
    service = AsyncMock(spec=MarketSyncService)
    service.sync_if_stale.side_effect = lambda hub: MarketSyncReport(hub_id=hub, items=1)
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=MarketSyncService)
    container = make_async_container(provider)
    redis = AsyncMock()
    redis.exists.side_effect = lambda key: key == "refresh:retry:market:jita"
    try:
        assert len(await worker.sync_markets({"container": container, "redis": redis})) == 4
        assert [call.args[0] for call in service.sync_if_stale.await_args_list] == [
            "amarr",
            "dodixie",
            "rens",
            "hek",
        ]
    finally:
        await container.close()
