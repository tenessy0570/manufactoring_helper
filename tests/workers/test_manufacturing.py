from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from arq import Retry
from dishka import Provider, Scope, make_async_container

from app.domains.catalog.repository import ItemTypeRepository
from app.domains.manufacturing.repository import ManufacturingRepository
from app.domains.manufacturing.service import ManufacturingSyncService
from app.workers import manufacturing as worker
from tests.domains.catalog.test_catalog import item
from tests.domains.manufacturing.test_manufacturing import recipe, recipe_state
from tests.helpers import make_settings


async def test_fresh_recipe_does_not_reserve_daily_job_before_it_expires() -> None:
    now = datetime.now(UTC)
    catalog = AsyncMock(spec=ItemTypeRepository)
    catalog.find.return_value = [item(10)]
    repository = AsyncMock(spec=ManufacturingRepository)
    state = recipe_state(expires_at=now + timedelta(hours=1))
    repository.recipes.return_value = {10: state}
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: catalog, provides=ItemTypeRepository)
    provider.provide(lambda: repository, provides=ManufacturingRepository)
    container = make_async_container(provider)
    redis = AsyncMock()
    try:
        context = {"container": container, "redis": redis}
        assert await worker.enqueue_manufacturing(context) == 0
        redis.enqueue_job.assert_not_awaited()
        state.expires_at = now - timedelta(seconds=1)
        assert await worker.enqueue_manufacturing(context) == 1
        assert redis.enqueue_job.await_args.args == ("sync_recipes", [10])
        redis.reset_mock()
        state.expires_at = now + timedelta(hours=1)
        state.recipe = recipe(estimated_item_value=None)
        assert await worker.enqueue_manufacturing(context) == 1
        redis.reset_mock()
        state.recipe = None
        assert await worker.enqueue_manufacturing(context) == 0
        redis.enqueue_job.assert_not_awaited()
    finally:
        await container.close()


async def test_queue_batches_and_deduplication() -> None:
    repository = AsyncMock(spec=ItemTypeRepository)
    repository.find.return_value = [item(number) for number in range(21)]
    recipes = AsyncMock(spec=ManufacturingRepository)
    recipes.recipes.return_value = {}
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: recipes, provides=ManufacturingRepository)
    provider.provide(lambda: repository, provides=ItemTypeRepository)
    container = make_async_container(provider)
    redis = AsyncMock()
    ctx = {"container": container, "redis": redis}
    assert await worker.enqueue_manufacturing(ctx) == 2
    assert repository.find.await_args is not None
    assert repository.find.await_args.args[0].meta_group_ids == [1, 2]
    ids = [call.kwargs["_job_id"] for call in redis.enqueue_job.await_args_list]
    assert len(set(ids)) == 2
    assert all(
        call.kwargs["_queue_name"] == worker.QUEUE for call in redis.enqueue_job.await_args_list
    )
    redis.reset_mock()
    redis.enqueue_job.return_value = None
    assert await worker.enqueue_manufacturing(ctx) == 0
    assert [call.kwargs["_job_id"] for call in redis.enqueue_job.await_args_list] == ids
    await container.close()


@pytest.mark.parametrize("attempt", [0, 1, 3])
async def test_batch_success_retry_and_failure(attempt: int) -> None:
    service = AsyncMock(spec=ManufacturingSyncService)
    service.sync_if_stale.side_effect = (
        [True, False] if attempt == 0 else [ConnectionError("offline"), True]
    )
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=ManufacturingSyncService)
    container = make_async_container(provider)
    ctx = {"container": container, "job_try": attempt}
    try:
        if attempt == 0:
            assert await worker.sync_recipes(ctx, [10, 20]) == 1
        elif attempt == 1:
            with pytest.raises(Retry):
                await worker.sync_recipes(ctx, [10, 20])
        else:
            with pytest.raises(RuntimeError, match="1 items"):
                await worker.sync_recipes(ctx, [10, 20])
        assert service.sync_if_stale.await_count == 2
    finally:
        await container.close()


async def test_worker_lifecycle_and_launcher(monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert calls[0]["queue_name"] == worker.QUEUE
    assert calls[0]["redis_settings"].host == settings.redis_host


async def test_ambiguous_recipe_does_not_fail_other_products() -> None:
    from app.domains.manufacturing.gateway import AmbiguousRecipeError

    service = AsyncMock(spec=ManufacturingSyncService)
    service.sync_if_stale.side_effect = [AmbiguousRecipeError("multiple blueprints"), True]
    provider = Provider(scope=Scope.REQUEST)
    provider.provide(lambda: service, provides=ManufacturingSyncService)
    container = make_async_container(provider)
    try:
        assert await worker.sync_recipes({"container": container}, [21527, 10]) == 1
    finally:
        await container.close()
