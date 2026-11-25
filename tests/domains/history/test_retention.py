from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from dishka import Provider, Scope, make_async_container
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import RefreshPolicy
from app.core.repository import UnitOfWork
from app.domains.history.gateway import HistoryGateway
from app.domains.history.models import HistoryDownload
from app.domains.history.repository import HistoryRepository, SQLHistoryRepository
from app.domains.history.retention import get_retention_cutoff
from app.domains.history.service import HistorySyncService
from app.workers.settings import prune_history
from tests.domains.catalog.test_catalog import NOW
from tests.domains.history.test_history import FakeRepository, day, get_state
from tests.domains.history.test_history import session as session


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (datetime(2026, 11, 25, tzinfo=UTC), "2025-11-25"),
        (datetime(2024, 2, 29, tzinfo=UTC), "2023-02-28"),
        (datetime(2025, 3, 31), "2024-03-31"),
    ],
)
def test_calendar_month_retention_handles_month_ends(now: datetime, expected: str) -> None:
    assert get_retention_cutoff(now, 12).isoformat() == expected


async def test_download_saves_only_completed_days_inside_retention() -> None:
    now = datetime(2026, 11, 25, tzinfo=UTC)
    cutoff = get_retention_cutoff(now, 12)
    repository = FakeRepository()
    gateway = AsyncMock(spec=HistoryGateway)
    gateway.fetch.return_value = HistoryDownload(
        days=[
            day(date=cutoff - timedelta(days=1)),
            day(date=cutoff),
            day(date=now.date() - timedelta(days=1)),
            day(date=now.date()),
        ],
        expires_at=now + timedelta(days=1),
    )
    service = HistorySyncService(repository, gateway, AsyncMock(spec=UnitOfWork), lambda: now)
    await service.sync_if_stale(10000002, 10)
    assert [row.date for row in repository.days] == [cutoff, now.date() - timedelta(days=1)]


async def test_global_pruning_keeps_boundary_and_updates_all_regions(session: AsyncSession) -> None:
    repository = SQLHistoryRepository(session)
    cutoff = get_retention_cutoff(NOW, 12)
    for region in (10000002, 10000043):
        await repository.replace(
            get_state(region), [day(date=cutoff - timedelta(days=1)), day(date=cutoff)]
        )
    unit_of_work = AsyncMock(spec=UnitOfWork)
    service = HistorySyncService(repository, AsyncMock(spec=HistoryGateway), unit_of_work)
    assert await service.prune_before(cutoff) == 2
    for region in (10000002, 10000043):
        saved = await repository.get_history_series(
            region, 10, cutoff - timedelta(days=1), NOW.date()
        )
        assert [row.date for row in saved] == [cutoff]
    unit_of_work.commit.assert_awaited_once()
    repository_mock = AsyncMock(spec=HistoryRepository)
    repository_mock.prune_before.side_effect = RuntimeError("write failed")
    failing = HistorySyncService(repository_mock, AsyncMock(spec=HistoryGateway), unit_of_work)
    with pytest.raises(RuntimeError):
        await failing.prune_before(cutoff)
    unit_of_work.rollback.assert_awaited_once()


async def test_cleanup_runs_once_per_cutoff_and_retries_failed_attempts() -> None:
    service = AsyncMock(spec=HistorySyncService)
    service.prune_before.return_value = 3
    provider = Provider(scope=Scope.APP)
    provider.provide(lambda: RefreshPolicy(), provides=RefreshPolicy)
    provider.provide(lambda: service, provides=HistorySyncService)
    container = make_async_container(provider)
    redis = AsyncMock()
    redis.get.return_value = None
    redis.exists.return_value = False
    ctx = {"container": container, "redis": redis}
    try:
        result = await prune_history(ctx)
        assert result["deleted"] == 3
        redis.get.return_value = result["cutoff"].encode()
        assert (await prune_history(ctx))["skipped"]
        service.prune_before.assert_awaited_once()
        redis.get.return_value = None
        redis.set.reset_mock()
        service.prune_before.side_effect = RuntimeError("offline")
        with pytest.raises(RuntimeError):
            await prune_history(ctx)
        assert all(
            call.args[0] != "history:retention:last_cutoff" for call in redis.set.await_args_list
        )
        redis.exists.return_value = True
        assert (await prune_history(ctx))["retry_delayed"]
    finally:
        await container.close()
