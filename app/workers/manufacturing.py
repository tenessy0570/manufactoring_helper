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
from app.domains.catalog.models import MASS_PRODUCTION_META_GROUP_IDS, ItemTypeClause
from app.domains.catalog.repository import ItemTypeRepository
from app.domains.manufacturing.gateway import AmbiguousRecipeError
from app.domains.manufacturing.service import ManufacturingSyncService

logger = logging.getLogger(__name__)

QUEUE = "arq:manufacturing"


async def enqueue_manufacturing(ctx: dict[str, Any]) -> int:
    container: AsyncContainer = ctx["container"]
    async with container() as scope:
        repository = await scope.get(ItemTypeRepository)
        ids = sorted(
            item.type_id
            for item in await repository.find(
                ItemTypeClause(meta_group_ids=list(MASS_PRODUCTION_META_GROUP_IDS))
            )
        )
    count = 0
    today = datetime.now(UTC).date().isoformat()
    for start in range(0, len(ids), 20):
        batch = ids[start : start + 20]
        digest = hashlib.sha256(",".join(map(str, batch)).encode()).hexdigest()[:16]
        job = await ctx["redis"].enqueue_job(
            "sync_recipes", batch, _queue_name=QUEUE, _job_id=f"manufacturing:{today}:{digest}"
        )
        count += job is not None
    return count


async def sync_recipes(ctx: dict[str, Any], type_ids: list[int]) -> int:
    container: AsyncContainer = ctx["container"]
    semaphore = asyncio.Semaphore(3)

    async def sync(type_id: int) -> bool:
        async with semaphore, container() as scope:
            service = await scope.get(ManufacturingSyncService)
            try:
                return await service.sync_if_stale(type_id)
            except AmbiguousRecipeError:
                logger.warning("Recipe skipped for product %s: multiple source blueprints", type_id)
                return False

    results = await asyncio.gather(*(sync(type_id) for type_id in type_ids), return_exceptions=True)
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        if ctx.get("job_try", 1) < 3:
            raise Retry(defer=60)
        raise RuntimeError(f"Manufacturing sync failed for {len(errors)} items") from errors[0]
    return sum(result is True for result in results)


async def startup(ctx: dict[str, Any]) -> None:
    ctx["container"] = create_container(get_settings())


async def shutdown(ctx: dict[str, Any]) -> None:
    container: AsyncContainer = ctx["container"]
    await container.close()


class ManufacturingWorkerSettings:
    functions = (sync_recipes,)
    queue_name = QUEUE
    on_startup = startup
    on_shutdown = shutdown
    max_jobs = 1
    max_tries = 3
    keep_result = 86400
    job_timeout = 900
    timezone = UTC


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    run_worker(
        {
            key: value
            for key, value in vars(ManufacturingWorkerSettings).items()
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
