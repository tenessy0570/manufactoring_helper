from abc import ABC, abstractmethod

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.catalog.tables import ItemTypeTable
from app.domains.health.models import DataProgress
from app.domains.history.tables import HistoryStateTable
from app.domains.invention.tables import InventionRequestTable
from app.domains.manufacturing.tables import RecipeTable
from app.domains.market.models import HubId, get_hub
from app.domains.market.tables import MarketStateTable


class ProgressRepository(ABC):
    @abstractmethod
    async def snapshot(self, hub: HubId) -> DataProgress: ...


class SQLProgressRepository(ProgressRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(self, hub: HubId) -> DataProgress:
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
                        InventionRequestTable.settings["order_type"].as_string() == "sell",
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
