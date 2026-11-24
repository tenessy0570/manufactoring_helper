from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.market.models import HubId, MarketPrice
from app.domains.market.tables import MarketPriceTable


class MarketQuoteReader(ABC):
    @abstractmethod
    async def quotes(self, hub_id: HubId, type_ids: Sequence[int]) -> dict[int, MarketPrice]: ...


class SQLMarketQuoteReader(MarketQuoteReader):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def quotes(self, hub_id: HubId, type_ids: Sequence[int]) -> dict[int, MarketPrice]:
        results: dict[int, MarketPrice] = {}
        for start in range(0, len(type_ids), 500):
            rows = await self._session.scalars(
                select(MarketPriceTable).where(
                    MarketPriceTable.hub_id == hub_id,
                    MarketPriceTable.type_id.in_(type_ids[start : start + 500]),
                )
            )
            for row in rows:
                quote = MarketPrice.model_validate(row, from_attributes=True)
                quote.expires_at = (
                    quote.expires_at.replace(tzinfo=UTC)
                    if quote.expires_at.tzinfo is None
                    else quote.expires_at
                )
                results[quote.type_id] = quote
        return results
