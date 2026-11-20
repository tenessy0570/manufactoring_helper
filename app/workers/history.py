import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from arq import Retry
from arq.connections import RedisSettings
from arq.worker import run_worker
from dishka import AsyncContainer

from app.core.config import get_settings
from app.core.di import create_container
from app.core.logging import configure_logging
from app.domains.catalog.models import ItemTypeClause
from app.domains.catalog.repository import ItemTypeRepository
from app.domains.history.repository import HistoryRepository
from app.domains.history.service import HistorySyncService
from app.domains.market.models import HUBS
from app.domains.trading.repository import TradingRepository

logger = logging.getLogger(__name__)
HISTORY_QUEUE = "arq:history"
BATCH_SIZE = 20


async def enqueue_history(ctx: dict[str, Any]) -> int:
    container: AsyncContainer = ctx["container"]
    async with container() as scope:
        repository = await scope.get(ItemTypeRepository)
        catalogue_ids = {item.type_id for item in await repository.find(ItemTypeClause())}
        market_ids = await (await scope.get(TradingRepository)).market_type_ids()
        ids = sorted(catalogue_ids | set(market_ids))
    count = 0
    now = datetime.now(UTC)
    for region_id in dict.fromkeys(hub.region_id for hub in HUBS):
        async with container() as scope:
            due = await (await scope.get(HistoryRepository)).due(region_id, ids, now)
        for start in range(0, len(ids), BATCH_SIZE):
            group = ids[start : start + BATCH_SIZE]
            batch = [type_id for type_id in group if type_id in due]
            if not batch:
                continue
            digest = hashlib.sha256(",".join(map(str, group)).encode()).hexdigest()[:16]
            job = await ctx["redis"].enqueue_job(
                "sync_history_batch",
                region_id,
                batch,
                _queue_name=HISTORY_QUEUE,
                _job_id=f"history:rolling:{region_id}:{digest}",
            )
            count += job is not None
    return count


async def sync_history_batch(ctx: dict[str, Any], region_id: int, type_ids: list[int]) -> int:
    container: AsyncContainer = ctx["container"]
    semaphore = asyncio.Semaphore(5)

    async def sync(type_id: int) -> bool:
        async with semaphore, container() as scope:
            service = await scope.get(HistorySyncService)
            return await service.sync_if_stale(region_id, type_id)

    results = await asyncio.gather(*(sync(type_id) for type_id in type_ids), return_exceptions=True)
    failures = [result for result in results if isinstance(result, BaseException)]
    if failures:
        logger.warning("History batch failed for region %s: %s items", region_id, len(failures))
        if ctx.get("job_try", 1) < 3:
            raise Retry(defer=60)
        raise RuntimeError(f"History sync failed for {len(failures)} items") from failures[0]
    return sum(result is True for result in results)


async def startup(ctx: dict[str, Any]) -> None:
    ctx["container"] = create_container(get_settings())


async def shutdown(ctx: dict[str, Any]) -> None:
    container: AsyncContainer = ctx["container"]
    await container.close()


class HistoryWorkerSettings:
    functions = (sync_history_batch,)
    queue_name = HISTORY_QUEUE
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 2
    max_tries = 3
    keep_result = 300
    job_timeout = 900
    timezone = UTC


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    run_worker(
        {
            key: value
            for key, value in vars(HistoryWorkerSettings).items()
            if not key.startswith("_")
        },
        redis_settings=RedisSettings(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password.get_secret_value(),
        ),
    )


if __name__ == "__main__":
    main()
