from typing import Any
from unittest.mock import AsyncMock

import pytest
from arq import Retry
from dishka import Provider, Scope, make_async_container

from app.domains.trading.repository import TradingRepository
from app.domains.trading.service import TradingMetadataService
from app.workers import trading as worker
from tests.helpers import make_settings


async def test_metadata_planner_only_due_ids_and_unique_batches() -> None:
    repository = AsyncMock(spec=TradingRepository)
    repository.market_type_ids.return_value = list(range(21))
    repository.due_metadata.return_value = list(range(21))
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: repository, provides=TradingRepository)
    container = make_async_container(provider)
    redis = AsyncMock()
    ctx = {"container": container, "redis": redis}
    assert await worker.enqueue_trade_metadata(ctx) == 2
    calls = redis.enqueue_job.await_args_list
    assert calls[0].args == ("sync_trade_metadata", list(range(20)))
    assert calls[1].args == ("sync_trade_metadata", [20])
    assert all(call.kwargs["_queue_name"] == worker.QUEUE for call in calls)
    ids = [call.kwargs["_job_id"] for call in calls]
    redis.reset_mock()
    redis.enqueue_job.return_value = None
    assert await worker.enqueue_trade_metadata(ctx) == 0
    assert [call.kwargs["_job_id"] for call in redis.enqueue_job.await_args_list] == ids
    repository.due_metadata.return_value = [20]
    redis.reset_mock()
    redis.enqueue_job.return_value = object()
    assert await worker.enqueue_trade_metadata(ctx) == 1
    assert redis.enqueue_job.await_args.args == ("sync_trade_metadata", [20])
    assert redis.enqueue_job.await_args.kwargs["_job_id"] == ids[1]
    repository.due_metadata.return_value = []
    assert await worker.enqueue_trade_metadata(ctx) == 0
    await container.close()


@pytest.mark.parametrize("attempt", [0, 1, 3])
async def test_metadata_batch_success_and_retry(attempt: int) -> None:
    service = AsyncMock(spec=TradingMetadataService)
    service.sync.side_effect = [True, False] if attempt == 0 else [ConnectionError("offline"), True]
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=TradingMetadataService)
    container = make_async_container(provider)
    try:
        ctx = {"container": container, "job_try": attempt}
        if attempt == 0:
            assert await worker.sync_trade_metadata(ctx, [10, 20]) == 1
        elif attempt == 1:
            with pytest.raises(Retry):
                await worker.sync_trade_metadata(ctx, [10, 20])
        else:
            with pytest.raises(RuntimeError, match="1 items"):
                await worker.sync_trade_metadata(ctx, [10, 20])
        assert service.sync.await_count == 2
    finally:
        await container.close()


async def test_worker_lifecycle_and_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    container = make_async_container()
    monkeypatch.setattr(worker, "get_settings", make_settings)
    monkeypatch.setattr(worker, "create_container", lambda settings: container)
    ctx: dict[str, Any] = {}
    await worker.startup(ctx)
    assert ctx["container"] is container
    await worker.shutdown(ctx)
    calls = []
    monkeypatch.setattr(
        worker, "run_worker", lambda config, **kwargs: calls.append((config, kwargs))
    )
    worker.main()
    assert calls[0][0]["queue_name"] == worker.QUEUE
    assert calls[0][0]["max_jobs"] == 2
    assert calls[0][0]["cron_jobs"][0].run_at_startup
