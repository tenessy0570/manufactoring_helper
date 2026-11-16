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
        esi = await scope.get(EsiClient)
        assert esi._http.headers["User-Agent"] == "eve-manufacturing"
    await container.close()
    assert esi._http.is_closed


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
    assert calls[0]["cron_jobs"][0].run_at_startup
