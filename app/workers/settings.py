import logging
from datetime import UTC, timedelta
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from arq.worker import run_worker
from dishka import AsyncContainer

from app.core.config import get_settings
from app.core.di import create_container
from app.core.logging import configure_logging
from app.domains.catalog.service import CatalogSyncService
from app.domains.market.models import HUBS
from app.domains.market.service import MarketSyncService
from app.workers.history import enqueue_history
from app.workers.invention import enqueue_inventions
from app.workers.manufacturing import enqueue_manufacturing

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    ctx["container"] = create_container(settings)
    ctx["catalog_max_age"] = timedelta(hours=settings.catalog_max_age_hours)


async def shutdown(ctx: dict[str, Any]) -> None:
    container: AsyncContainer = ctx["container"]
    await container.close()


async def sync_catalog(ctx: dict[str, Any]) -> dict[str, Any]:
    container: AsyncContainer = ctx["container"]
    async with container() as scope:
        service = await scope.get(CatalogSyncService)
        return (await service.sync_if_stale(ctx["catalog_max_age"])).model_dump()


async def sync_markets(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    container: AsyncContainer = ctx["container"]
    reports: list[dict[str, Any]] = []
    failures: list[str] = []
    for hub in HUBS:
        try:
            async with container() as scope:
                service = await scope.get(MarketSyncService)
                reports.append((await service.sync_if_stale(hub.hub_id)).model_dump())
        except Exception:
            failures.append(hub.hub_id)
            logger.exception("Market sync failed for %s", hub.hub_id)
    if failures:
        raise RuntimeError(f"Market sync failed for hubs: {', '.join(failures)}")
    return reports


class WorkerSettings:
    functions = (
        sync_catalog,
        sync_markets,
        enqueue_history,
        enqueue_manufacturing,
        enqueue_inventions,
    )
    cron_jobs = (
        cron(sync_catalog, hour=4, minute=0, run_at_startup=True),
        cron(sync_markets, minute=0, run_at_startup=True),
        cron(enqueue_history, hour=12, minute=15, run_at_startup=True),
        cron(enqueue_manufacturing, minute=20, run_at_startup=True),
        cron(enqueue_inventions, hour=12, minute=30, run_at_startup=True),
    )
    on_startup = startup
    on_shutdown = shutdown
    timezone = UTC
    max_jobs = 1
    job_timeout = 3600


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    run_worker(
        {key: value for key, value in vars(WorkerSettings).items() if not key.startswith("_")},
        redis_settings=RedisSettings(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password.get_secret_value(),
        ),
    )


if __name__ == "__main__":
    main()
