from unittest.mock import AsyncMock

import pytest

from app.core.cache import Cache
from app.core.repository import SQLAlchemyUnitOfWork
from app.domains.health.models import FreshnessReport, SourceFreshness
from app.domains.health.repository import ProgressRepository
from app.domains.health.service import ProgressService
from app.domains.market.progress import MarketSyncProgress
from app.domains.market.service import MarketSyncService
from tests.domains.market.test_market import NOW, FakeGateway, FakeRepository


@pytest.mark.parametrize("failed", [False, True])
async def test_sync_publishes_page_progress_and_clears_on_success_or_failure(failed: bool) -> None:
    progress = AsyncMock(spec=MarketSyncProgress)
    service = MarketSyncService(
        FakeRepository(),
        FakeGateway(failed),
        AsyncMock(spec=SQLAlchemyUnitOfWork),
        lambda: NOW,
        progress=progress,
    )
    if failed:
        with pytest.raises(ConnectionError):
            await service.sync("jita")
    else:
        await service.sync("jita")
        progress.update.assert_any_await("jita", 2, 2)
    progress.update.assert_any_await("jita", 1, 2)
    progress.clear.assert_awaited_once_with("jita")


async def test_progress_is_shared_by_hub_and_added_to_freshness_without_changing_snapshot() -> None:
    cache = AsyncMock(spec=Cache)
    progress = MarketSyncProgress(cache)
    await progress.update("jita", 25, 100)
    cache.set.assert_awaited_once_with("market-sync-progress:jita", [25, 100], 300)
    cache.get.return_value = [25, 100]
    repository = AsyncMock(spec=ProgressRepository)
    repository.get_freshness_report.return_value = FreshnessReport(
        hub_id="jita",
        checked_at=NOW,
        sources=[
            SourceFreshness(
                source="market", oldest_at=NOW, newest_at=NOW, cached=1000, fresh=0, status="stale"
            )
        ],
    )
    report = await ProgressService(repository, progress).get_freshness_report("jita")
    assert report.sources[0].completed_pages == 25
    assert report.sources[0].total_pages == 100
    assert report.sources[0].fresh == 0
    await progress.clear("jita")
    cache.delete.assert_awaited_once_with("market-sync-progress:jita")


@pytest.mark.parametrize("value", [None, {}, [1], [1, 0], ["bad", 100]])
async def test_missing_or_invalid_progress_is_ignored(value: object) -> None:
    cache = AsyncMock(spec=Cache)
    cache.get.return_value = value
    assert await MarketSyncProgress(cache).get("amarr") is None
