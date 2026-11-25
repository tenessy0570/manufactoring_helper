from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.domains.market.models import HubId, MarketPrice, MarketState, PriceQuery
from app.domains.market.tables import MarketPriceTable, MarketStateTable


class MarketRepository(ABC):
    @abstractmethod
    async def get_state(self, hub_id: HubId) -> MarketState | None: ...

    @abstractmethod
    async def replace(self, state: MarketState, prices: Sequence[MarketPrice]) -> None: ...

    @abstractmethod
    async def find(self, query: PriceQuery, now: datetime) -> list[MarketPrice]: ...

    @abstractmethod
    async def count(self, query: PriceQuery, now: datetime) -> int: ...


class SQLMarketRepository(MarketRepository):
    def __init__(
        self, session: AsyncSession, refresh_policy: RefreshPolicy = DEFAULT_REFRESH
    ) -> None:
        self._session = session
        self._refresh_policy = refresh_policy

    async def get_state(self, hub_id: HubId) -> MarketState | None:
        row = await self._session.get(MarketStateTable, hub_id)
        if row is None:
            return None
        state = MarketState.model_validate(row, from_attributes=True)
        for name in ("synced_at", "expires_at"):
            value = getattr(state, name)
            if value.tzinfo is None:
                setattr(state, name, value.replace(tzinfo=UTC))
        return state

    async def replace(self, state: MarketState, prices: Sequence[MarketPrice]) -> None:
        if any(price.hub_id != state.hub_id for price in prices):
            raise ValueError("Snapshot contains a different hub")
        await self._session.execute(
            delete(MarketPriceTable).where(MarketPriceTable.hub_id == state.hub_id)
        )
        for start in range(0, len(prices), 100):
            self._session.add_all(
                MarketPriceTable(
                    **price.model_dump(exclude={"buy_levels", "sell_levels"}),
                    sell_levels=None
                    if price.sell_levels is None
                    else [level.model_dump(mode="json") for level in price.sell_levels],
                    buy_levels=None
                    if price.buy_levels is None
                    else [level.model_dump(mode="json") for level in price.buy_levels],
                )
                for price in prices[start : start + 100]
            )
            await self._session.flush()
        await self._session.merge(MarketStateTable(**state.model_dump()))
        await self._session.flush()

    def _build_conditions(self, query: PriceQuery, now: datetime) -> list[ColumnElement[bool]]:
        table = MarketPriceTable
        conditions: list[ColumnElement[bool]] = [table.hub_id == query.hub_id]
        if query.type_ids is not None:
            conditions.append(table.type_id.in_(query.type_ids))
        if query.exclude_type_ids is not None:
            conditions.append(table.type_id.not_in(query.exclude_type_ids))
        for column, low, high in (
            (table.buy_price, query.min_buy_price, query.max_buy_price),
            (table.sell_price, query.min_sell_price, query.max_sell_price),
            (table.spread, query.min_spread, query.max_spread),
            (table.buy_volume, query.min_buy_volume, None),
            (table.sell_volume, query.min_sell_volume, None),
        ):
            if low is not None:
                conditions.append(column >= low)
            if high is not None:
                conditions.append(column <= high)
        for column, present in (
            (table.buy_price, query.has_buy),
            (table.sell_price, query.has_sell),
        ):
            if present is not None:
                conditions.append(column.is_not(None) if present else column.is_(None))
        if query.fresh_only:
            conditions.append(table.synced_at > now - self._refresh_policy.market)
        return conditions

    async def find(self, query: PriceQuery, now: datetime) -> list[MarketPrice]:
        rows = await self._session.scalars(
            select(MarketPriceTable)
            .where(*self._build_conditions(query, now))
            .order_by(MarketPriceTable.type_id)
            .limit(query.limit)
            .offset(query.offset)
        )
        return [MarketPrice.model_validate(row, from_attributes=True) for row in rows]

    async def count(self, query: PriceQuery, now: datetime) -> int:
        return (
            await self._session.scalar(
                select(func.count())
                .select_from(MarketPriceTable)
                .where(*self._build_conditions(query, now))
            )
            or 0
        )
