import asyncio
from collections.abc import Callable
from datetime import UTC, datetime

from app.core.freshness import MARKET_FRESHNESS, refresh_deadline
from app.core.repository import UnitOfWork
from app.domains.market.aggregation import PriceAggregator
from app.domains.market.gateway import MarketGateway
from app.domains.market.models import (
    HubId,
    MarketState,
    MarketSyncReport,
    PricePage,
    PriceQuery,
    get_hub,
)
from app.domains.market.repository import MarketRepository


class MarketPaginationChangedError(ValueError):
    pass


class MarketService:
    def __init__(self, repository: MarketRepository) -> None:
        self._repository = repository

    async def find(self, query: PriceQuery) -> PricePage:
        now = datetime.now(UTC)
        state = await self._repository.state(query.hub_id)
        return PricePage(
            hub=get_hub(query.hub_id),
            state=state,
            stale=state is None or refresh_deadline(state.synced_at, MARKET_FRESHNESS) <= now,
            items=await self._repository.find(query, now),
            total=await self._repository.count(query, now),
            limit=query.limit,
            offset=query.offset,
        )


class MarketSyncService:
    def __init__(
        self,
        repository: MarketRepository,
        gateway: MarketGateway,
        unit_of_work: UnitOfWork,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._uow = unit_of_work
        self._clock = clock

    async def sync_if_stale(self, hub_id: HubId) -> MarketSyncReport:
        state = await self._repository.state(hub_id)
        if state is not None and state.expires_at > self._clock():
            return MarketSyncReport(hub_id=hub_id, skipped=True, items=state.items)
        return await self.sync(hub_id)

    async def sync(self, hub_id: HubId) -> MarketSyncReport:
        for attempt in range(3):
            try:
                return await self._sync_snapshot(hub_id)
            except MarketPaginationChangedError:
                if attempt == 2:
                    raise
                await asyncio.sleep(1)
        raise AssertionError("Unreachable")

    async def _sync_snapshot(self, hub_id: HubId) -> MarketSyncReport:
        hub = get_hub(hub_id)
        synced_at = self._clock()
        first = await self._gateway.get_orders(hub.region_id, 1)
        pages, expires_at = first.pages, first.expires_at
        aggregator = PriceAggregator(hub, synced_at, expires_at)
        for order in first.orders:
            aggregator.add(order)
        del first
        for start in range(2, pages + 1, 5):
            page_numbers = range(start, min(start + 5, pages + 1))
            results = await asyncio.gather(
                *(self._gateway.get_orders(hub.region_id, page) for page in page_numbers),
                return_exceptions=True,
            )
            for page, batch in zip(page_numbers, results, strict=True):
                if isinstance(batch, BaseException):
                    raise batch
                if batch.pages != pages or batch.page != page:
                    raise MarketPaginationChangedError(
                        "Market pagination changed during sync; previous snapshot preserved"
                    )
                expires_at = min(expires_at, batch.expires_at)
                for order in batch.orders:
                    aggregator.add(order)
        prices = aggregator.finish(expires_at)
        state = MarketState(
            hub_id=hub_id, synced_at=synced_at, expires_at=expires_at, items=len(prices)
        )
        try:
            await self._repository.replace(state, prices)
            await self._uow.commit()
        except BaseException:
            await self._uow.rollback()
            raise
        return MarketSyncReport(hub_id=hub_id, items=len(prices), pages=pages)
