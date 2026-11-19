from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from arq import Retry
from dishka import Provider, Scope, make_async_container

from app.core.repository import UnitOfWork
from app.domains.catalog.repository import ItemTypeRepository
from app.domains.invention.queue import InventionQueue
from app.domains.invention.repository import InventionRepository
from app.domains.invention.service import InventionSyncService
from app.workers import invention as worker
from tests.domains.catalog.test_catalog import item
from tests.domains.invention.test_invention import request, settings
from tests.helpers import make_settings


class FakeRedis:
    def __init__(self) -> None:
        self.keys: list[str] = []

    @asynccontextmanager
    async def lock(self, key: str, **kwargs: Any) -> AsyncIterator[None]:
        self.keys.append(key)
        yield


@pytest.mark.parametrize("attempt", [0, 1, 3])
async def test_worker_reuses_shared_plan_lock_and_records_failure(attempt: int) -> None:
    service = AsyncMock(spec=InventionSyncService)
    service.sync.return_value = request()
    if attempt:
        service.sync.side_effect = ConnectionError("offline")
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=InventionSyncService)
    container = make_async_container(provider)
    redis = FakeRedis()
    ctx = {"container": container, "redis": redis, "job_try": attempt}
    try:
        if attempt == 0:
            assert await worker.sync_invention(ctx, settings().model_dump(mode="json")) == "ready"
            service.record_error.assert_not_awaited()
        else:
            with pytest.raises(Retry if attempt == 1 else ConnectionError):
                await worker.sync_invention(ctx, settings().model_dump(mode="json"))
            service.record_error.assert_awaited_once_with(settings(), "ConnectionError")
        assert redis.keys == [f"invention:plan:{settings().plan_key}"]
    finally:
        await container.close()


async def test_planner_skips_fresh_and_refreshes_requested_profiles() -> None:
    repository = AsyncMock(spec=InventionRepository)
    catalog = AsyncMock(spec=ItemTypeRepository)
    queue = AsyncMock(spec=InventionQueue)
    uow = AsyncMock(spec=UnitOfWork)
    catalog.find.return_value = [item(10), item(20)]
    custom = settings(type_id=30, hub_id="amarr")
    repository.active_settings.return_value = [custom]
    repository.requests.return_value = {
        settings().key: request(expires_at=datetime.now(UTC) + timedelta(days=1))
    }
    queue.enqueue.return_value = True
    queue.enqueue_catalog.return_value = True
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: repository, provides=InventionRepository)
    provider.provide(lambda: catalog, provides=ItemTypeRepository)
    provider.provide(lambda: queue, provides=InventionQueue)
    provider.provide(lambda: uow, provides=UnitOfWork)
    container = make_async_container(provider)
    try:
        assert await worker.enqueue_inventions({"container": container})
        assert await worker.schedule_inventions({"container": container}) == 2
        assert {call.args[0].type_id for call in queue.enqueue.await_args_list} == {20, 30}
        uow.commit.assert_awaited_once()
        queue.reset_mock()
        assert await worker.schedule_inventions({"container": container}, {"hub_id": "hek"}) == 2
        assert {call.args[0].hub_id for call in queue.enqueue.await_args_list} == {"hek"}
    finally:
        await container.close()


async def test_worker_lifecycle_and_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    container = make_async_container()
    config = make_settings()
    monkeypatch.setattr(worker, "get_settings", lambda: config)
    monkeypatch.setattr(worker, "create_container", lambda settings: container)
    ctx: dict[str, Any] = {}
    await worker.startup(ctx)
    assert ctx["container"] is container
    await worker.shutdown(ctx)
    calls: list[dict[str, Any]] = []

    def run(settings: dict[str, Any], **kwargs: Any) -> None:
        calls.append({**settings, **kwargs})

    monkeypatch.setattr(worker, "run_worker", run)
    worker.main()
    assert calls[0]["queue_name"] == "arq:invention"
    assert calls[0]["keep_result"] == 0
    assert calls[0]["redis_settings"].host == config.redis_host


async def test_planner_respects_persisted_failure_retry_deadline() -> None:
    repository = AsyncMock(spec=InventionRepository)
    catalog = AsyncMock(spec=ItemTypeRepository)
    queue = AsyncMock(spec=InventionQueue)
    uow = AsyncMock(spec=UnitOfWork)
    catalog.find.return_value = [item(10)]
    repository.active_settings.return_value = []
    failed = request(status="error", expires_at=datetime.now(UTC) + timedelta(minutes=5))
    repository.requests.return_value = {settings().key: failed}
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: repository, provides=InventionRepository)
    provider.provide(lambda: catalog, provides=ItemTypeRepository)
    provider.provide(lambda: queue, provides=InventionQueue)
    provider.provide(lambda: uow, provides=UnitOfWork)
    container = make_async_container(provider)
    try:
        assert await worker.schedule_inventions({"container": container}) == 0
        queue.enqueue.assert_not_awaited()
        failed.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        queue.enqueue.return_value = True
        assert await worker.schedule_inventions({"container": container}) == 1
    finally:
        await container.close()
