from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.core.freshness import get_refresh_deadline
from app.core.repository import UnitOfWork
from app.domains.history.gateway import HistoryGateway
from app.domains.history.models import HistorySeries, HistoryState, LiquidityPage, LiquidityQuery
from app.domains.history.repository import HistoryRepository
from app.domains.history.retention import get_retention_cutoff
from app.domains.market.models import HubId, get_hub


class HistoryService:
    def __init__(
        self,
        repository: HistoryRepository,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        refresh_policy: RefreshPolicy = DEFAULT_REFRESH,
    ) -> None:
        self._repository, self._clock = repository, clock
        self._refresh_policy = refresh_policy

    async def get_liquidity(self, query: LiquidityQuery) -> LiquidityPage:
        now = self._clock()
        items, total = await self._repository.get_liquidity(query, now)
        return LiquidityPage(
            hub=get_hub(query.hub_id),
            days=query.days,
            start_date=now.date() - timedelta(days=query.days),
            end_date=now.date() - timedelta(days=1),
            items=items,
            total=total,
            limit=query.limit,
            offset=query.offset,
        )

    async def get_history_series(self, hub_id: HubId, type_id: int, days: int) -> HistorySeries:
        hub, now = get_hub(hub_id), self._clock()
        state = await self._repository.get_state(hub.region_id, type_id)
        return HistorySeries(
            hub=hub,
            type_id=type_id,
            state=state,
            stale=state is None
            or get_refresh_deadline(state.synced_at, self._refresh_policy.history) <= now,
            days=await self._repository.get_history_series(
                hub.region_id,
                type_id,
                now.date() - timedelta(days=days),
                now.date() - timedelta(days=1),
            ),
        )


class HistorySyncService:
    def __init__(
        self,
        repository: HistoryRepository,
        gateway: HistoryGateway,
        unit_of_work: UnitOfWork,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        refresh_policy: RefreshPolicy = DEFAULT_REFRESH,
    ) -> None:
        self._refresh_policy = refresh_policy
        self._repository, self._gateway, self._unit_of_work, self._clock = (
            repository,
            gateway,
            unit_of_work,
            clock,
        )

    async def sync_if_stale(self, region_id: int, type_id: int) -> bool:
        state = await self._repository.get_state(region_id, type_id)
        now = self._clock()
        if (
            state is not None
            and max(
                state.expires_at,
                get_refresh_deadline(state.synced_at, self._refresh_policy.history),
            )
            > now
        ):
            return False
        downloaded = await self._gateway.fetch(region_id, type_id)
        # Ignore incomplete current-day data; averages always use completed UTC days.
        cutoff = get_retention_cutoff(now, self._refresh_policy.history_retention_months)
        days = [day for day in downloaded.days if cutoff <= day.date < now.date()]
        state = HistoryState(
            region_id=region_id,
            type_id=type_id,
            synced_at=self._clock(),
            expires_at=downloaded.expires_at,
        )
        try:
            await self._repository.replace(state, days)
            await self._unit_of_work.commit()
        except BaseException:
            await self._unit_of_work.rollback()
            raise
        return True

    async def prune_before(self, cutoff: date) -> int:
        try:
            deleted = await self._repository.prune_before(cutoff)
            await self._unit_of_work.commit()
            return deleted
        except BaseException:
            await self._unit_of_work.rollback()
            raise
