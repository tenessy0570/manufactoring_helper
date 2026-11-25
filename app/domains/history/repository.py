from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from typing import cast as typing_cast

from sqlalchemy import ColumnElement, CursorResult, Numeric, Select, cast, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.domains.catalog.tables import ItemTypeTable
from app.domains.history.models import HistoryDay, HistoryState, LiquidityItem, LiquidityQuery
from app.domains.history.tables import HistoryDayTable, HistoryStateTable
from app.domains.market.models import get_hub


class HistoryRepository(ABC):
    @abstractmethod
    async def get_state(self, region_id: int, type_id: int) -> HistoryState | None: ...

    @abstractmethod
    async def replace(self, state: HistoryState, days: Sequence[HistoryDay]) -> None: ...

    @abstractmethod
    async def find_due_type_ids(
        self, region_id: int, type_ids: Sequence[int], now: datetime
    ) -> set[int]: ...

    @abstractmethod
    async def get_history_series(
        self, region_id: int, type_id: int, start: date, end: date
    ) -> list[HistoryDay]: ...

    @abstractmethod
    async def get_liquidity(
        self, query: LiquidityQuery, now: datetime
    ) -> tuple[list[LiquidityItem], int]: ...

    @abstractmethod
    async def find_candidates(self, query: LiquidityQuery, now: datetime) -> list[LiquidityItem]:
        """All matching items for evaluation, without a page limit or a separate count."""
        ...

    @abstractmethod
    async def prune_before(self, cutoff: date) -> int: ...


class SQLHistoryRepository(HistoryRepository):
    def __init__(
        self, session: AsyncSession, refresh_policy: RefreshPolicy = DEFAULT_REFRESH
    ) -> None:
        self._session = session
        self._refresh_policy = refresh_policy

    async def get_state(self, region_id: int, type_id: int) -> HistoryState | None:
        row = await self._session.get(HistoryStateTable, (region_id, type_id))
        if row is None:
            return None
        state = HistoryState.model_validate(row, from_attributes=True)
        for name in ("synced_at", "expires_at"):
            value = getattr(state, name)
            if value.tzinfo is None:
                setattr(state, name, value.replace(tzinfo=UTC))
        return state

    async def find_due_type_ids(
        self, region_id: int, type_ids: Sequence[int], now: datetime
    ) -> set[int]:
        fresh: set[int] = set()
        for start in range(0, len(type_ids), 500):
            rows = await self._session.scalars(
                select(HistoryStateTable.type_id).where(
                    HistoryStateTable.region_id == region_id,
                    HistoryStateTable.type_id.in_(type_ids[start : start + 500]),
                    (HistoryStateTable.expires_at > now)
                    | (HistoryStateTable.synced_at > now - self._refresh_policy.history),
                )
            )
            fresh.update(rows)
        return set(type_ids) - fresh

    async def replace(self, state: HistoryState, days: Sequence[HistoryDay]) -> None:
        await self._session.execute(
            delete(HistoryDayTable).where(
                HistoryDayTable.region_id == state.region_id,
                HistoryDayTable.type_id == state.type_id,
            )
        )
        for start in range(0, len(days), 100):
            self._session.add_all(
                HistoryDayTable(
                    region_id=state.region_id, type_id=state.type_id, **day.model_dump()
                )
                for day in days[start : start + 100]
            )
            await self._session.flush()
        await self._session.merge(HistoryStateTable(**state.model_dump()))
        await self._session.flush()

    async def get_history_series(
        self, region_id: int, type_id: int, start: date, end: date
    ) -> list[HistoryDay]:
        rows = await self._session.scalars(
            select(HistoryDayTable)
            .where(
                HistoryDayTable.region_id == region_id,
                HistoryDayTable.type_id == type_id,
                HistoryDayTable.date >= start,
                HistoryDayTable.date <= end,
            )
            .order_by(HistoryDayTable.date)
        )
        return [HistoryDay.model_validate(row, from_attributes=True) for row in rows]

    def _build_catalog_conditions(self, query: LiquidityQuery) -> list[ColumnElement[bool]]:
        items = ItemTypeTable
        conditions: list[ColumnElement[bool]] = [items.is_active.is_(True)]
        if query.type_ids is not None:
            conditions.append(items.type_id.in_(query.type_ids))
        if query.exclude_type_ids is not None:
            conditions.append(items.type_id.not_in(query.exclude_type_ids))
        if query.search is not None:
            conditions.append(items.name.icontains(query.search, autoescape=True))
        for column, values in (
            (items.category, query.categories),
            (items.meta_group_id, query.meta_group_ids),
        ):
            if values is not None:
                conditions.append(column.in_(values))
        if query.is_rig is not None:
            conditions.append(items.is_rig == query.is_rig)
        return conditions

    def _build_liquidity_statement(self, query: LiquidityQuery, now: datetime) -> Select[Any]:
        history, states, items = HistoryDayTable, HistoryStateTable, ItemTypeTable
        region = get_hub(query.hub_id).region_id
        start, end = now.date() - timedelta(days=query.days), now.date() - timedelta(days=1)
        item_conditions = self._build_catalog_conditions(query)
        conditions = [
            history.region_id == region,
            history.date >= start,
            history.date <= end,
            history.type_id.in_(select(items.type_id).where(*item_conditions)),
        ]
        totals = (
            select(
                history.type_id.label("type_id"),
                func.count().label("data_days"),
                cast(
                    func.sum(history.average * history.volume) / Decimal(query.days), Numeric(38, 8)
                ).label("daily_isk_volume"),
                cast(func.sum(history.volume) / Decimal(query.days), Numeric(38, 8)).label(
                    "daily_units"
                ),
                func.max(history.date).label("latest_trade_date"),
            )
            .where(*conditions)
            .group_by(history.type_id)
            .subquery()
        )
        statement = (
            select(
                items.type_id,
                items.name,
                items.meta_group_id,
                func.coalesce(totals.c.data_days, 0).label("data_days"),
                totals.c.daily_isk_volume,
                totals.c.daily_units,
                totals.c.latest_trade_date,
                states.synced_at,
                states.expires_at,
            )
            .outerjoin(totals, totals.c.type_id == items.type_id)
            .outerjoin(
                states,
                (states.type_id == items.type_id) & (states.region_id == region),
            )
            .where(*item_conditions)
        )
        for metric, low, high in (
            (totals.c.daily_isk_volume, query.min_daily_isk_volume, query.max_daily_isk_volume),
            (totals.c.daily_units, query.min_daily_units, query.max_daily_units),
        ):
            if low is not None:
                statement = statement.where(metric >= low)
            if high is not None:
                statement = statement.where(metric <= high)
        if query.has_history is not None:
            statement = statement.where(
                totals.c.type_id.is_not(None) if query.has_history else totals.c.type_id.is_(None)
            )
        if query.fresh_only:
            statement = statement.where(states.synced_at > now - self._refresh_policy.history)
        return statement

    async def get_liquidity(
        self, query: LiquidityQuery, now: datetime
    ) -> tuple[list[LiquidityItem], int]:
        statement = self._build_liquidity_statement(query, now)
        total = (
            await self._session.scalar(select(func.count()).select_from(statement.subquery())) or 0
        )
        rows = (
            await self._session.execute(
                statement.order_by(ItemTypeTable.type_id).limit(query.limit).offset(query.offset)
            )
        ).mappings()
        return [LiquidityItem.model_validate(dict(row)) for row in rows], total

    async def find_candidates(self, query: LiquidityQuery, now: datetime) -> list[LiquidityItem]:
        rows = (
            await self._session.execute(
                self._build_liquidity_statement(query, now).order_by(ItemTypeTable.type_id)
            )
        ).mappings()
        return [LiquidityItem.model_validate(dict(row)) for row in rows]

    async def prune_before(self, cutoff: date) -> int:
        result = await self._session.execute(
            delete(HistoryDayTable).where(HistoryDayTable.date < cutoff)
        )
        return typing_cast(CursorResult[Any], result).rowcount
