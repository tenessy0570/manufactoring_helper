from typing import Any
from unittest.mock import AsyncMock

import pytest
from arq import Retry
from dishka import Provider, Scope, make_async_container

from app.domains.catalog.repository import ItemTypeRepository
from app.domains.history.repository import HistoryRepository
from app.domains.history.service import HistorySyncService
from app.workers import history as worker
from tests.domains.catalog.test_catalog import item
from tests.helpers import make_settings


async def test_enqueue_batches_are_unique_and_use_separate_queue() -> None:
    repository = AsyncMock(spec=ItemTypeRepository)
    repository.find.return_value = [item(number) for number in range(21)]
    history = AsyncMock(spec=HistoryRepository)
    history.due.return_value = set(range(21))
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: history, provides=HistoryRepository)
    provider.provide(lambda: repository, provides=ItemTypeRepository)
    container = make_async_container(provider)
    redis = AsyncMock()
    redis.enqueue_job.return_value = object()
    ctx = {"container": container, "redis": redis}
    assert await worker.enqueue_history(ctx) == 10
    assert repository.find.await_args is not None
    assert repository.find.await_args.args[0].meta_group_ids == [1, 2]
    first_ids = [call.kwargs["_job_id"] for call in redis.enqueue_job.await_args_list]
    assert len(set(first_ids)) == 10
    assert all(
        call.kwargs["_queue_name"] == worker.HISTORY_QUEUE
        for call in redis.enqueue_job.await_args_list
    )
    redis.reset_mock()
    redis.enqueue_job.return_value = None
    assert await worker.enqueue_history(ctx) == 0
    assert [call.kwargs["_job_id"] for call in redis.enqueue_job.await_args_list] == first_ids
    history.due.return_value = {20}
    redis.reset_mock()
    redis.enqueue_job.return_value = object()
    assert await worker.enqueue_history(ctx) == 5
    assert all(call.args[2] == [20] for call in redis.enqueue_job.await_args_list)
    assert {call.kwargs["_job_id"] for call in redis.enqueue_job.await_args_list} <= set(first_ids)
    history.due.return_value = set()
    redis.reset_mock()
    assert await worker.enqueue_history(ctx) == 0
    redis.enqueue_job.assert_not_awaited()
    repository.find.return_value = []
    redis.reset_mock()
    assert await worker.enqueue_history(ctx) == 0
    redis.enqueue_job.assert_not_awaited()
    await container.close()


@pytest.mark.parametrize("attempt", [0, 1, 3])
async def test_batch_sync_and_retries(attempt: int) -> None:
    service = AsyncMock(spec=HistorySyncService)
    service.sync_if_stale.side_effect = (
        [True, False] if attempt == 0 else [ConnectionError("offline"), True]
    )
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=HistorySyncService)
    container = make_async_container(provider)
    try:
        ctx = {"container": container, "job_try": attempt}
        if attempt == 0:
            assert await worker.sync_history_batch(ctx, 10000002, [10, 20]) == 1
        elif attempt == 1:
            with pytest.raises(Retry):
                await worker.sync_history_batch(ctx, 10000002, [10, 20])
        else:
            with pytest.raises(RuntimeError, match="1 items"):
                await worker.sync_history_batch(ctx, 10000002, [10, 20])
        assert service.sync_if_stale.await_count == 2
    finally:
        await container.close()


async def test_worker_lifecycle_and_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    container = make_async_container()
    settings = make_settings()
    monkeypatch.setattr(worker, "get_settings", lambda: settings)
    monkeypatch.setattr(worker, "create_container", lambda settings: container)
    ctx: dict[str, Any] = {}
    await worker.startup(ctx)
    assert ctx["container"] is container
    await worker.shutdown(ctx)
    calls: list[dict[str, Any]] = []

    def run(config: dict[str, Any], **kwargs: Any) -> None:
        calls.append({**config, **kwargs})

    monkeypatch.setattr(worker, "run_worker", run)
    worker.main()
    assert calls[0]["queue_name"] == worker.HISTORY_QUEUE
    assert calls[0]["redis_settings"].host == settings.redis_host
