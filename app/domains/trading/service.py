from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.core.freshness import get_refresh_deadline
from app.core.repository import UnitOfWork
from app.domains.catalog.names import ItemNameService, ItemNamesUnavailableError
from app.domains.market.models import get_hub
from app.domains.trading.calculation import calculate_trade
from app.domains.trading.gateway import TradingGateway
from app.domains.trading.models import TradeMetadata, TradingPage, TradingQuery
from app.domains.trading.repository import TradingRepository
from app.domains.trading.routes import TradingRoutes


class TradingService:
    def __init__(
        self,
        repository: TradingRepository,
        names: ItemNameService | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        routes: TradingRoutes | None = None,
        refresh_policy: RefreshPolicy = DEFAULT_REFRESH,
    ) -> None:
        self._routes = routes
        self._refresh_policy = refresh_policy
        self._repository, self._names, self._clock = repository, names, clock

    async def get_opportunities(self, query: TradingQuery) -> TradingPage:
        now = self._clock()
        turnover_minimum = query.min_daily_isk_volume if query.filter_daily_turnover else None
        inputs = await self._repository.get_trade_inputs(query)
        missing_metadata = len(
            {value.source.type_id for value in inputs if value.metadata_expires_at is None}
        )
        missing_volume = len({value.source.type_id for value in inputs if value.volume_m3 is None})
        items = []
        for value in inputs:
            if query.search and (
                value.name is None or query.search.casefold() not in value.name.casefold()
            ):
                continue
            result = calculate_trade(value, query, now, self._refresh_policy)
            if result is not None:
                items.append(result)
        turnover = await self._repository.get_turnover(
            query, sorted({item.type_id for item in items}), now
        )
        route_data = {}
        if self._routes is not None:
            for source_hub, destination_hub in sorted(
                {(item.source_hub, item.destination_hub) for item in items}
            ):
                route_data[source_hub, destination_hub] = await self._routes.get_cached_route(
                    source_hub, destination_hub, query.route_mode
                )
        missing_routes = set()
        filtered = []
        missing_history = set()
        for item in items:
            route = route_data.get((item.source_hub, item.destination_hub))
            if route is not None:
                if route.jumps is None:
                    missing_routes.add((item.source_hub, item.destination_hub))
                    continue
                item.jumps = route.jumps
                item.route_highsec = route.highsec
                if item.batch_profit is not None:
                    item.profit_per_jump = item.batch_profit / route.jumps
            if query.max_jumps is not None and (item.jumps is None or item.jumps > query.max_jumps):
                continue
            if query.min_profit_per_jump is not None and (
                item.profit_per_jump is None or item.profit_per_jump < query.min_profit_per_jump
            ):
                continue
            key = (get_hub(item.destination_hub).region_id, item.type_id)
            record = turnover.get(key)
            if record is None:
                missing_history.add(key)
                if turnover_minimum is not None or query.price_spikes_only:
                    continue
            else:
                if query.price_spikes_only:
                    baseline = record.median_price
                    if baseline is None or baseline <= 0 or record.baseline_days < 3:
                        continue
                    item.historical_median_price = baseline
                    item.price_spike_pct = (item.sale_price / baseline - 1) * 100
                    if (
                        item.price_spike_pct <= 0
                        or item.price_spike_pct < query.price_spike_threshold
                    ):
                        continue
                item.daily_isk_volume = record.daily_isk_volume
                item.history_updated_at = record.updated_at
                if turnover_minimum is not None and record.daily_isk_volume < turnover_minimum:
                    continue
                if get_refresh_deadline(record.updated_at, self._refresh_policy.history) <= now:
                    item.stale = True
                    if query.fresh_only:
                        continue
            filtered.append(item)
        items = filtered
        attribute = {
            "batch_profit": "batch_profit",
            "profit": "profit_per_unit",
            "margin": "margin_pct",
            "profit_per_m3": "profit_per_m3",
            "profit_per_jump": "profit_per_jump",
            "jumps": "jumps",
        }[query.rank_by]
        items.sort(
            key=lambda value: (
                getattr(value, attribute) is None,
                (1 if attribute == "jumps" else -1) * (getattr(value, attribute) or Decimal(0)),
                value.type_id,
                value.source_hub,
                value.destination_hub,
            )
        )
        total = len(items)
        page = items[query.offset : query.offset + query.limit]
        unknown = sorted({item.type_id for item in page if item.name == "Loading item name..."})
        if unknown and self._names is not None:
            try:
                resolved = await self._names.resolve(unknown)
                for item in page:
                    item.name = resolved.names.get(item.type_id, item.name)
            except ItemNamesUnavailableError:
                pass
        source, destination = await self._repository.get_snapshot_times(query)
        return TradingPage(
            source_hub=query.source_hub,
            destination_hub=query.destination_hub,
            items=page,
            total=total,
            limit=query.limit,
            offset=query.offset,
            scanned=len(inputs),
            missing_metadata=missing_metadata,
            missing_volume=missing_volume,
            missing_history=len(missing_history),
            missing_routes=len(missing_routes),
            source_updated_at=source,
            destination_updated_at=destination,
        )


class TradingMetadataService:
    def __init__(
        self,
        repository: TradingRepository,
        gateway: TradingGateway,
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

    async def sync(self, type_id: int) -> bool:
        previous = await self._repository.get_metadata(type_id)
        now = self._clock()
        if previous is not None and previous.expires_at > now:
            return False
        details = await self._gateway.get_type_details(type_id)
        now = self._clock()
        metadata = TradeMetadata(
            type_id=type_id,
            name=details.name,
            volume_m3=details.packaged_volume
            if details.packaged_volume is not None
            else details.volume,
            updated_at=now,
            expires_at=now + timedelta(seconds=self._refresh_policy.metadata_seconds),
        )
        try:
            await self._repository.save_metadata(metadata)
            await self._unit_of_work.commit()
        except BaseException:
            await self._unit_of_work.rollback()
            raise
        return True
