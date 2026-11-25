import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from app.core.concurrency import gather_all
from app.core.repository import Page, UnitOfWork
from app.domains.catalog.gateway import CatalogGateway
from app.domains.catalog.models import CatalogPage, CatalogSyncReport, ItemType, ItemTypeClause
from app.domains.catalog.repository import ItemTypeRepository
from app.domains.catalog.selector import MarketTreeSelector

logger = logging.getLogger(__name__)


class CatalogService:
    def __init__(self, repository: ItemTypeRepository) -> None:
        self._repository = repository

    async def find(self, clause: ItemTypeClause, page: Page) -> CatalogPage:
        return CatalogPage(
            items=await self._repository.find(clause, page),
            total=await self._repository.count(clause),
            limit=page.limit,
            offset=page.offset,
        )


class CatalogSyncService:
    def __init__(
        self,
        repository: ItemTypeRepository,
        gateway: CatalogGateway,
        unit_of_work: UnitOfWork,
        selector: MarketTreeSelector,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._unit_of_work = unit_of_work
        self._selector = selector
        self._clock = clock

    async def sync_if_stale(self, max_age: timedelta) -> CatalogSyncReport:
        latest = await self._repository.get_latest_sync_time()
        if latest is not None and self._clock() - latest < max_age:
            return CatalogSyncReport(skipped=True)
        return await self.sync()

    async def sync(self) -> CatalogSyncReport:
        synced_at = self._clock()
        ids = sorted(set(await self._gateway.list_market_group_ids()))
        groups = await gather_all(self._gateway.get_market_group(group_id) for group_id in ids)
        if any(group is None for group in groups):
            raise ValueError("Market group disappeared during sync; retry the complete catalog")
        candidates = self._selector.select([group for group in groups if group is not None])
        if not candidates:
            raise ValueError("Empty catalog; previous data preserved")
        existing = {
            item.type_id: item
            for item in await self._repository.find(ItemTypeClause(is_active=None))
        }
        names = await self._gateway.resolve_names(
            [item.type_id for item in candidates if item.type_id not in existing]
        )

        async def build(type_id: int) -> int | None:
            previous = existing.get(type_id)
            if previous is not None and previous.meta_group_id is not None:
                return previous.meta_group_id
            try:
                return await self._gateway.get_meta_group_id(type_id)
            except Exception:
                logger.warning("Metadata unavailable for type %s", type_id, exc_info=True)
                return None

        metadata = await gather_all(build(item.type_id) for item in candidates)
        items = []
        for candidate, meta in zip(candidates, metadata, strict=True):
            previous = existing.get(candidate.type_id)
            name = previous.name if previous is not None else names.get(candidate.type_id)
            if name is None:
                raise ValueError(f"Missing name for type {candidate.type_id}")
            items.append(
                ItemType(
                    **candidate.model_dump(), name=name, meta_group_id=meta, synced_at=synced_at
                )
            )
        try:
            await self._repository.upsert_many(items)
            await self._repository.deactivate_before(synced_at)
            await self._unit_of_work.commit()
        except BaseException:
            await self._unit_of_work.rollback()
            raise
        return CatalogSyncReport(
            items=len(items), missing_metadata=sum(item.meta_group_id is None for item in items)
        )
