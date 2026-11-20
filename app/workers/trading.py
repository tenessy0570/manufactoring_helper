import asyncio
import hashlib
import logging
from datetime import UTC, datetime
from typing import Any

from arq import Retry, cron
from arq.connections import RedisSettings
from arq.worker import run_worker
from dishka import AsyncContainer

from app.core.config import get_settings
from app.core.di import create_container
from app.core.logging import configure_logging
from app.domains.trading.models import RouteMode
from app.domains.trading.repository import TradingRepository
from app.domains.trading.routes import SYSTEMS, TradingRoutes
from app.domains.trading.service import TradingMetadataService

logger = logging.getLogger(__name__)
QUEUE = "arq:trading"


async def enqueue_trade_metadata(ctx: dict[str, Any]) -> int:
    container: AsyncContainer = ctx["container"]
    async with container() as scope:
        repository = await scope.get(TradingRepository)
        ids = await repository.market_type_ids()
        due = set(await repository.due_metadata(datetime.now(UTC)))
    count = 0
    for start in range(0, len(ids), 20):
        group = ids[start : start + 20]
        pending = [value for value in group if value in due]
        if not pending:
            continue
        digest = hashlib.sha256(",".join(map(str, group)).encode()).hexdigest()[:16]
        job = await ctx["redis"].enqueue_job(
            "sync_trade_metadata", group, _queue_name=QUEUE, _job_id="trade:metadata:" + digest
        )
        count += job is not None
    logger.info("Trade metadata: %s items due, %s batches queued", len(due), count)
    return count


async def sync_trade_metadata(ctx: dict[str, Any], type_ids: list[int]) -> int:
    container: AsyncContainer = ctx["container"]
    semaphore = asyncio.Semaphore(3)

    async def sync(type_id: int) -> bool:
        async with semaphore, container() as scope:
            return await (await scope.get(TradingMetadataService)).sync(type_id)

    results = await asyncio.gather(*(sync(value) for value in type_ids), return_exceptions=True)
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        if ctx.get("job_try", 1) < 3:
            raise Retry(defer=60)
        raise RuntimeError(f"Trade metadata failed for {len(errors)} items") from errors[0]
    return sum(result is True for result in results)


async def refresh_trade_routes(ctx: dict[str, Any]) -> None:
    container: AsyncContainer = ctx["container"]
    routes = await container.get(TradingRoutes)
    for source in SYSTEMS:
        for destination in SYSTEMS:
            if source == destination:
                continue
            for mode in ("safe", "shortest"):
                route_mode: RouteMode = mode
                await routes.refresh(source, destination, route_mode)


async def startup(ctx: dict[str, Any]) -> None:
    ctx["container"] = create_container(get_settings())


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["container"].close()


class TradingWorkerSettings:
    functions = (sync_trade_metadata,)
    cron_jobs = (
        cron(
            refresh_trade_routes,
            minute=set(range(0, 60, 5)),
            run_at_startup=True,
            job_id="trade:routes",
        ),
        cron(
            enqueue_trade_metadata,
            minute=set(range(60)),
            run_at_startup=True,
            job_id="trade:metadata:planner",
        ),
    )
    queue_name = QUEUE
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 2
    max_tries = 3
    keep_result = 0
    job_timeout = 900
    timezone = UTC


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    run_worker(
        {
            key: value
            for key, value in vars(TradingWorkerSettings).items()
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
