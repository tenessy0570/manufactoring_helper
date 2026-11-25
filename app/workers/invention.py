from datetime import UTC, datetime
from typing import Any

from arq import Retry
from arq.connections import RedisSettings
from arq.worker import run_worker
from dishka import AsyncContainer

from app.core.config import get_settings
from app.core.di import create_container
from app.core.logging import configure_logging
from app.core.repository import UnitOfWork
from app.domains.catalog.models import ItemTypeClause
from app.domains.catalog.repository import ItemTypeRepository
from app.domains.invention.models import QUEUE, InventionQuery, InventionRequest, InventionSettings
from app.domains.invention.queue import InventionQueue
from app.domains.invention.repository import InventionRepository
from app.domains.invention.service import InventionSyncService


async def enqueue_inventions(ctx: dict[str, Any]) -> bool:
    container: AsyncContainer = ctx["container"]
    async with container() as scope:
        queue: InventionQueue = await scope.get(InventionQueue)
        return await queue.enqueue_catalog()


async def schedule_inventions(ctx: dict[str, Any], query: dict[str, Any] | None = None) -> int:
    container: AsyncContainer = ctx["container"]
    now = datetime.now(UTC)
    async with container() as scope:
        catalog = await scope.get(ItemTypeRepository)
        repository = await scope.get(InventionRepository)
        selected = InventionQuery.model_validate(query or {})
        settings = {
            value.key: value
            for value in (
                InventionSettings(type_id=item.type_id, **selected.model_dump())
                for item in await catalog.find(ItemTypeClause(meta_group_ids=[2]))
            )
        }
        if query is None:
            settings.update({value.key: value for value in await repository.get_active_settings()})
        previous = await repository.get_requests(list(settings))
        pending: list[InventionSettings] = []
        for key, value in settings.items():
            existing = previous.get(key)
            if (
                existing is not None
                and existing.expires_at > now
                and existing.status in ("ready", "unsupported", "error", "missing_prices")
            ):
                continue
            await repository.ensure_request(
                InventionRequest(key=key, settings=value, updated_at=now, expires_at=now)
            )
            pending.append(value)
        await (await scope.get(UnitOfWork)).commit()
        queue = await scope.get(InventionQueue)
        return sum([await queue.enqueue(value) for value in pending])


async def sync_invention(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    settings = InventionSettings.model_validate(payload)
    container: AsyncContainer = ctx["container"]
    try:
        # A profile's source plans are shared across hubs, order sides and price requests.
        async with (
            ctx["redis"].lock(
                f"invention:plan:{settings.plan_key}", timeout=600, blocking_timeout=10
            ),
            container() as scope,
        ):
            service = await scope.get(InventionSyncService)
            return (await service.sync(settings)).status
    except Exception as error:
        async with container() as scope:
            await (await scope.get(InventionSyncService)).record_error(
                settings, type(error).__name__
            )
        if ctx.get("job_try", 1) < 3:
            raise Retry(defer=60) from error
        raise


async def startup(ctx: dict[str, Any]) -> None:
    ctx["container"] = create_container(get_settings())


async def shutdown(ctx: dict[str, Any]) -> None:
    container: AsyncContainer = ctx["container"]
    await container.close()


class InventionWorkerSettings:
    functions = (schedule_inventions, sync_invention)
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
            for key, value in vars(InventionWorkerSettings).items()
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
