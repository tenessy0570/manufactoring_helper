from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from statistics import median

from sqlalchemy import Numeric, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.tables import ItemTypeTable
from app.domains.history.tables import HistoryDayTable, HistoryStateTable
from app.domains.market.models import HUBS, MarketPrice
from app.domains.market.tables import MarketPriceTable, MarketStateTable
from app.domains.trading.models import TradeInput, TradeMetadata, TradeTurnover, TradingQuery
from app.domains.trading.tables import TradeMetadataTable


class TradingRepository(ABC):
    @abstractmethod
    async def get_turnover(
        self, query: TradingQuery, type_ids: list[int], now: datetime
    ) -> dict[tuple[int, int], TradeTurnover]: ...

    @abstractmethod
    async def get_trade_inputs(self, query: TradingQuery) -> list[TradeInput]: ...

    @abstractmethod
    async def get_market_type_ids(self) -> list[int]: ...

    @abstractmethod
    async def find_due_metadata_ids(self, now: datetime) -> list[int]: ...

    @abstractmethod
    async def get_metadata(self, type_id: int) -> TradeMetadata | None: ...

    @abstractmethod
    async def save_metadata(self, metadata: TradeMetadata) -> None: ...

    @abstractmethod
    async def get_snapshot_times(
        self, query: TradingQuery
    ) -> tuple[datetime | None, datetime | None]: ...


def ensure_utc(stamp: datetime | None) -> datetime | None:
    return stamp.replace(tzinfo=UTC) if stamp is not None and stamp.tzinfo is None else stamp


class SQLTradingRepository(TradingRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_trade_inputs(self, query: TradingQuery) -> list[TradeInput]:
        hubs = (
            [query.source_hub, query.destination_hub]
            if query.source_hub and query.destination_hub
            else [hub.hub_id for hub in HUBS]
        )
        statement = (
            select(
                MarketPriceTable,
                func.coalesce(TradeMetadataTable.name, ItemTypeTable.name),
                TradeMetadataTable.volume_m3,
                TradeMetadataTable.expires_at,
            )
            .outerjoin(TradeMetadataTable, TradeMetadataTable.type_id == MarketPriceTable.type_id)
            .outerjoin(ItemTypeTable, ItemTypeTable.type_id == MarketPriceTable.type_id)
            .where(MarketPriceTable.hub_id.in_(hubs))
            .order_by(MarketPriceTable.type_id, MarketPriceTable.hub_id)
        )
        prices: dict[int, list[MarketPrice]] = {}
        details: dict[int, tuple[str | None, Decimal | None, datetime | None]] = {}
        for row, name, volume, expiry in (await self._session.execute(statement)).all():
            prices.setdefault(row.type_id, []).append(
                MarketPrice.model_validate(row, from_attributes=True)
            )
            details[row.type_id] = name, volume, ensure_utc(expiry)
        results = []
        for type_id, quotes in prices.items():
            item_name, item_volume, metadata_expiry = details[type_id]
            for source in quotes:
                if query.source_hub is not None and source.hub_id != query.source_hub:
                    continue
                for destination in quotes:
                    if source.hub_id == destination.hub_id:
                        continue
                    if (
                        query.destination_hub is not None
                        and destination.hub_id != query.destination_hub
                    ):
                        continue
                    results.append(
                        TradeInput(
                            source=source,
                            destination=destination,
                            name=item_name,
                            volume_m3=item_volume,
                            metadata_expires_at=metadata_expiry,
                        )
                    )
        return results

    async def get_turnover(
        self, query: TradingQuery, type_ids: list[int], now: datetime
    ) -> dict[tuple[int, int], TradeTurnover]:
        if not type_ids:
            return {}
        regions = [
            hub.region_id
            for hub in HUBS
            if query.destination_hub is None or hub.hub_id == query.destination_hub
        ]
        history, states = HistoryDayTable, HistoryStateTable
        totals = (
            select(
                history.region_id,
                history.type_id,
                cast(
                    func.sum(history.average * history.volume) / Decimal(query.history_days),
                    Numeric(38, 8),
                ).label("daily_isk_volume"),
            )
            .where(
                history.region_id.in_(regions),
                history.type_id.in_(type_ids),
                history.date >= now.date() - timedelta(days=query.history_days),
                history.date < now.date(),
            )
            .group_by(history.region_id, history.type_id)
            .subquery()
        )
        statement = (
            select(
                states.region_id,
                states.type_id,
                states.synced_at,
                func.coalesce(totals.c.daily_isk_volume, 0).label("daily_isk_volume"),
            )
            .outerjoin(
                totals,
                (totals.c.region_id == states.region_id) & (totals.c.type_id == states.type_id),
            )
            .where(states.region_id.in_(regions), states.type_id.in_(type_ids))
        )
        result = {
            (region, type_id): TradeTurnover(
                type_id=type_id,
                region_id=region,
                daily_isk_volume=volume,
                updated_at=ensure_utc(stamp),
            )
            for region, type_id, stamp, volume in (await self._session.execute(statement)).all()
        }
        if query.price_spikes_only:
            baseline_statement = select(history.region_id, history.type_id, history.average).where(
                history.region_id.in_(regions),
                history.type_id.in_(type_ids),
                history.date >= now.date() - timedelta(days=7),
                history.date < now.date(),
                history.average > 0,
                history.volume > 0,
            )
            prices: dict[tuple[int, int], list[Decimal]] = {}
            for region, type_id, average in (await self._session.execute(baseline_statement)).all():
                prices.setdefault((region, type_id), []).append(average)
            for key, values in prices.items():
                if key in result:
                    result[key].median_price = median(values)
                    result[key].baseline_days = len(values)
        return result

    async def get_market_type_ids(self) -> list[int]:
        return list(
            await self._session.scalars(
                select(MarketPriceTable.type_id).distinct().order_by(MarketPriceTable.type_id)
            )
        )

    async def find_due_metadata_ids(self, now: datetime) -> list[int]:
        statement = (
            select(MarketPriceTable.type_id)
            .distinct()
            .outerjoin(TradeMetadataTable, TradeMetadataTable.type_id == MarketPriceTable.type_id)
            .where((TradeMetadataTable.type_id.is_(None)) | (TradeMetadataTable.expires_at <= now))
            .order_by(MarketPriceTable.type_id)
        )
        return list(await self._session.scalars(statement))

    async def get_metadata(self, type_id: int) -> TradeMetadata | None:
        row = await self._session.get(TradeMetadataTable, type_id)
        if row is None:
            return None
        return TradeMetadata(
            type_id=row.type_id,
            name=row.name,
            volume_m3=row.volume_m3,
            updated_at=ensure_utc(row.updated_at),
            expires_at=ensure_utc(row.expires_at),
        )

    async def save_metadata(self, metadata: TradeMetadata) -> None:
        await self._session.merge(TradeMetadataTable(**metadata.model_dump()))
        await self._session.flush()

    async def get_snapshot_times(
        self, query: TradingQuery
    ) -> tuple[datetime | None, datetime | None]:
        rows = dict(
            (
                await self._session.execute(
                    select(MarketStateTable.hub_id, MarketStateTable.synced_at)
                )
            ).all()
        )
        sources = [
            hub.hub_id
            for hub in HUBS
            if (query.source_hub is None or hub.hub_id == query.source_hub)
            and hub.hub_id != query.destination_hub
        ]
        destinations = [
            hub.hub_id
            for hub in HUBS
            if (query.destination_hub is None or hub.hub_id == query.destination_hub)
            and hub.hub_id != query.source_hub
        ]

        def get_oldest_snapshot_time(hubs: Sequence[str]) -> datetime | None:
            if any(hub not in rows for hub in hubs):
                return None
            return ensure_utc(min(rows[hub] for hub in hubs)) if hubs else None

        return get_oldest_snapshot_time(sources), get_oldest_snapshot_time(destinations)
