from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import DEFAULT_REFRESH, RefreshPolicy
from app.domains.catalog.tables import ItemTypeTable
from app.domains.health.models import DataProgress, FreshnessReport, SourceFreshness
from app.domains.history.tables import HistoryStateTable
from app.domains.invention.tables import InventionRequestTable
from app.domains.manufacturing.tables import RecipeTable
from app.domains.market.enums import OrderSide
from app.domains.market.models import HubId, get_hub
from app.domains.market.tables import MarketStateTable


class ProgressRepository(ABC):
    @abstractmethod
    async def get_freshness_report(self, hub: HubId, now: datetime) -> FreshnessReport: ...

    @abstractmethod
    async def get_data_progress(self, hub: HubId) -> DataProgress: ...


class SQLProgressRepository(ProgressRepository):
    def __init__(
        self, session: AsyncSession, refresh_policy: RefreshPolicy = DEFAULT_REFRESH
    ) -> None:
        self._session = session
        self._refresh_policy = refresh_policy

    async def get_data_progress(self, hub: HubId) -> DataProgress:
        eligible = select(ItemTypeTable.type_id).where(
            ItemTypeTable.is_active.is_(True), ItemTypeTable.meta_group_id.in_([1, 2])
        )
        total = await self._session.scalar(select(func.count()).select_from(eligible.subquery()))
        t2 = await self._session.scalar(
            select(func.count())
            .select_from(ItemTypeTable)
            .where(ItemTypeTable.type_id.in_(eligible), ItemTypeTable.meta_group_id == 2)
        )
        recipes = await self._session.scalar(
            select(func.count())
            .select_from(RecipeTable)
            .where(RecipeTable.type_id.in_(eligible), RecipeTable.recipe.is_not(None))
        )
        unavailable = await self._session.scalar(
            select(func.count())
            .select_from(RecipeTable)
            .where(RecipeTable.type_id.in_(eligible), RecipeTable.recipe.is_(None))
        )
        history = await self._session.scalar(
            select(func.count())
            .select_from(HistoryStateTable)
            .where(
                HistoryStateTable.type_id.in_(eligible),
                HistoryStateTable.region_id == get_hub(hub).region_id,
            )
        )
        statuses = dict(
            (
                await self._session.execute(
                    select(InventionRequestTable.status, func.count())
                    .where(
                        InventionRequestTable.settings["hub_id"].as_string() == hub,
                        InventionRequestTable.settings["order_type"].as_string()
                        == OrderSide.SELL.value,
                        InventionRequestTable.settings["type_id"].as_integer().in_(eligible),
                    )
                    .group_by(InventionRequestTable.status)
                )
            ).all()
        )
        market = await self._session.get(MarketStateTable, hub)
        return DataProgress(
            catalog_items=total or 0,
            recipes_loaded=recipes or 0,
            recipes_unavailable=unavailable or 0,
            history_loaded=history or 0,
            t2_items=t2 or 0,
            invention_ready=statuses.get("ready", 0),
            invention_pending=statuses.get("pending", 0),
            invention_unsupported=statuses.get("unsupported", 0),
            invention_errors=statuses.get("error", 0) + statuses.get("missing_prices", 0),
            market_items=market.items if market else 0,
            market_updated_at=market.synced_at if market else None,
        )

    async def get_freshness_report(self, hub: HubId, now: datetime) -> FreshnessReport:
        sources = []
        specifications: list[tuple[str, Any, Any, Any, list[Any]]] = [
            (
                "market",
                MarketStateTable,
                MarketStateTable.synced_at,
                MarketStateTable.synced_at > now - self._refresh_policy.market,
                [MarketStateTable.hub_id == hub],
            ),
            (
                "history",
                HistoryStateTable,
                HistoryStateTable.synced_at,
                HistoryStateTable.synced_at > now - self._refresh_policy.history,
                [HistoryStateTable.region_id == get_hub(hub).region_id],
            ),
            (
                "recipes",
                RecipeTable,
                RecipeTable.synced_at,
                and_(
                    RecipeTable.expires_at > now,
                    or_(
                        RecipeTable.recipe.is_(None),
                        RecipeTable.recipe["estimated_item_value"].as_string().is_not(None),
                    ),
                ),
                [],
            ),
            (
                "invention",
                InventionRequestTable,
                InventionRequestTable.updated_at,
                InventionRequestTable.expires_at > now,
                [
                    InventionRequestTable.status == "ready",
                    InventionRequestTable.result.is_not(None),
                    InventionRequestTable.settings["hub_id"].as_string() == hub,
                    InventionRequestTable.settings["order_type"].as_string()
                    == OrderSide.SELL.value,
                ],
            ),
        ]
        for name, table, stamp, fresh_condition, conditions in specifications:
            row = (
                await self._session.execute(
                    select(
                        func.count(),
                        func.min(stamp),
                        func.max(stamp),
                        func.sum(case((fresh_condition, 1), else_=0)),
                    )
                    .select_from(table)
                    .where(*conditions)
                )
            ).one()
            count, oldest, newest, fresh = row
            fresh = fresh or 0
            sources.append(
                SourceFreshness(
                    source=name,
                    cached=count,
                    fresh=fresh,
                    oldest_at=oldest.replace(tzinfo=UTC)
                    if oldest and oldest.tzinfo is None
                    else oldest,
                    newest_at=newest.replace(tzinfo=UTC)
                    if newest and newest.tzinfo is None
                    else newest,
                    status="missing"
                    if not count
                    else "fresh"
                    if fresh == count
                    else "partial"
                    if fresh
                    else "stale",
                )
            )
        return FreshnessReport(hub_id=hub, checked_at=now, sources=sources)
