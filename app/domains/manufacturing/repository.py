from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.manufacturing.models import RecipeState
from app.domains.manufacturing.tables import RecipeTable
from app.domains.market.models import HubId, MarketPrice
from app.domains.market.quotes import MarketQuoteReader

_RECIPES = TypeAdapter(list[RecipeState])


class ManufacturingRepository(ABC):
    @abstractmethod
    async def recipes(self, type_ids: Sequence[int]) -> dict[int, RecipeState]: ...

    @abstractmethod
    async def save(self, state: RecipeState) -> None: ...

    @abstractmethod
    async def quotes(self, hub_id: HubId, type_ids: Sequence[int]) -> dict[int, MarketPrice]: ...


class SQLManufacturingRepository(ManufacturingRepository):
    def __init__(self, session: AsyncSession, quotes: MarketQuoteReader) -> None:
        self._session, self._quotes = session, quotes

    async def recipes(self, type_ids: Sequence[int]) -> dict[int, RecipeState]:
        results: dict[int, RecipeState] = {}
        for start in range(0, len(type_ids), 500):
            rows = await self._session.execute(
                select(RecipeTable.__table__).where(
                    RecipeTable.type_id.in_(type_ids[start : start + 500])
                )
            )
            for state in _RECIPES.validate_python(rows.mappings().all()):
                state.synced_at = (
                    state.synced_at.replace(tzinfo=UTC)
                    if state.synced_at.tzinfo is None
                    else state.synced_at
                )
                state.expires_at = (
                    state.expires_at.replace(tzinfo=UTC)
                    if state.expires_at.tzinfo is None
                    else state.expires_at
                )
                results[state.type_id] = state
        return results

    async def save(self, state: RecipeState) -> None:
        await self._session.merge(
            RecipeTable(
                type_id=state.type_id,
                recipe=None if state.recipe is None else state.recipe.model_dump(mode="json"),
                synced_at=state.synced_at,
                expires_at=state.expires_at,
            )
        )
        await self._session.flush()

    async def quotes(self, hub_id: HubId, type_ids: Sequence[int]) -> dict[int, MarketPrice]:
        return await self._quotes.quotes(hub_id, type_ids, include_sell_levels=False)
